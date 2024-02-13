#!/usr/bin/env python3

import asyncio
import click
import datetime
import os
import sys
from google.protobuf import text_format
from libikawa import *

@click.group()
@click.pass_context
@click.option("--debug", is_flag=True)
def main(ctx, debug):
	"""CLI tool to interact with the Ikawa Home roaster."""
	if not debug:
		sys.tracebacklimit = 0
	ctx.obj = { "log_level": 2 if debug else 1 }

async def get_info(log_level):
	async with Ikawa(log_level=log_level, log_target=sys.stderr) as ikawa:
		resp = await ikawa.send_cmd(Cmd(cmd_type=BOOTLOADER_GET_VERSION))
		bootloader_version = f"{resp.resp_bootloader_get_version.version}.{resp.resp_bootloader_get_version.revision}"
		resp = await ikawa.send_cmd(Cmd(cmd_type=MACH_PROP_GET_TYPE))
		machine_type = f"{RespMachPropGetType.MachVariant.Name(resp.resp_mach_prop_type.variant)} {RespMachPropGetType.MachType.Name(resp.resp_mach_prop_type.type)}"
		resp = await ikawa.send_cmd(Cmd(cmd_type=MACH_PROP_GET_ID))
		machine_id = f"{resp.resp_mach_id.id}"
		return { "BOOTLOADER_VERSION": bootloader_version, "MACHINE_TYPE": machine_type, "MACHINE_ID": machine_id }

async def get_settings(log_level):
	def intBitsToFloat(b):
		s = struct.pack('>l', b)
		return struct.unpack('>f', s)[0]
	
	settings = dict()
	async with Ikawa(log_level=log_level, log_target=sys.stderr) as ikawa:
		resp = await ikawa.send_cmd(Cmd(cmd_type=SETTING_GET_LIST, setting_get_list=CmdSettingGetList(offset=0)))
		for i in resp.resp_setting_get_list.number:
			resp = await ikawa.send_cmd(Cmd(cmd_type=SETTING_GET_INFO, setting_get_info=CmdSettingGetInfo(number=i)))
			info = resp.resp_setting_get_info
			resp = await ikawa.send_cmd(Cmd(cmd_type=SETTING_GET, setting_get=CmdSettingGet(number=i)))
			value = resp.resp_setting_get.val_u32_float if info.type == FLOAT else resp.resp_setting_get.val_u32
			settings[info.name] = value
	return settings

@click.command()
@click.pass_context
@click.option("--settings", is_flag=True)
def info(ctx, settings):
	"""Get infos about the roaster. By default fetches machine and bootloader properties, or roaster settings if --settings flag is set."""
	if settings:
		info = asyncio.run(get_settings(ctx.obj["log_level"]))
	else:
		info = asyncio.run(get_info(ctx.obj["log_level"]))
	for key, value in info.items():
			print(f"{key}: {value}")

async def get_profile(log_level):
	async with Ikawa(log_level=log_level, log_target=sys.stderr) as ikawa:
		resp = await ikawa.send_cmd(Cmd(cmd_type=PROFILE_GET))
		return resp.resp_profile_get.profile

async def set_profile(profile, log_level):
	async with Ikawa(log_level=log_level, log_target=sys.stderr) as ikawa:
		resp = await ikawa.send_cmd(Cmd(cmd_type=PROFILE_SET, profile_set=CmdProfileSet(profile=profile)))
		if resp.resp != 1:
			raise RuntimeError("Setting profile failed")
		print("Profile set")

@click.command()
@click.pass_context
@click.option("--set", "send", is_flag=True, help="Send profile to roaster")
@click.option("--url", "profile_url", help="Load profile from URL or plain base64 profile")
@click.option("--file", "file_path", help="Parse a roast profile from the given file")
@click.option("--no-confirm", is_flag=True, help="Send profile directly to roaster without asking for confirmation")
@click.option("--quiet", is_flag=True, help="Don't print profile")
def profile(ctx, profile_url, file_path, send, no_confirm, quiet):
	"""Get or set the roast profile. By default fetches the currently loaded profile from the roaster and displays it. The --set option allows to send a profile to the roaster instead."""
	profile = None
	if profile_url:
		profile = Ikawa.roast_profile_from_url(profile_url)
	elif file_path:
		with open(file_path, 'r') as file:
			str = file.read()
			profile = text_format.Parse(str, RoastProfile())
			if not profile.schema:
				profile.schema = 1
			if not profile.id:
				profile.id = os.urandom(16)
			if not profile.temp_sensor:
				profile.temp_sensor = RoastProfile.TempSensor.BELOW_BEANS

	if send:
		if not profile:
			raise RuntimeError("No profile loaded, --url or --yml required")
		if not quiet:
			print(profile)
		if no_confirm or click.confirm('Send this profile to the roaster?', default=False):
			asyncio.run(set_profile(profile, ctx.obj["log_level"]))
		else:
			exit(1)
	else:
		if not profile:
			profile = asyncio.run(get_profile(ctx.obj["log_level"]))
		if not quiet:
			print(profile)

async def log_sensors(log_level):
	async with Ikawa(retry_timeout=1, log_level=log_level, log_target=sys.stderr) as ikawa:
		cmd = Cmd(cmd_type=MACH_STATUS_GET_ALL)
		while True:
			try:
				resp = await ikawa.send_cmd(cmd)
				status = resp.resp_mach_status_get_all
				real_time = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0).isoformat()
				print(f"{real_time}, {status.time*0.1:.1f}, {MachState.Name(status.state)}, {status.temp_below*0.1:.1f}, {status.setpoint*0.1:.1f}, {status.heater}, {status.fan/255.0:.2f}, {status.fan_measured}", flush=True)
			except TimeoutError:
				pass
			await asyncio.sleep(0.1)

@click.command()
@click.pass_context
@click.option("--no-header", is_flag=True, help="Don't print CSV table header")
def log(ctx, no_header):
	"""Watch the roaster sensors, logging in CSV format to stdout"""
	if not no_header:
		print("real time, roast time, roaster state, temperature °C, setpoint target temperature °C, heater, setpoint fan power %, fan measured")
	try:
		asyncio.run(log_sensors(ctx.obj["log_level"]))
	except KeyboardInterrupt:
		pass

main.add_command(info)
main.add_command(profile)
main.add_command(log)

if __name__ == '__main__':
	main()
