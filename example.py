#!/usr/bin/env python3

import asyncio
import time
from libikawa import *

async def main():
	async with Ikawa() as ikawa:
		cmd = Cmd(cmd_type=BOOTLOADER_GET_VERSION)
		resp = await ikawa.send_cmd(cmd)
		print(resp)
		cmd = Cmd(cmd_type=MACH_PROP_GET_TYPE)
		resp = await ikawa.send_cmd(cmd)
		print(resp)
		cmd = Cmd(cmd_type=PROFILE_GET)
		resp = await ikawa.send_cmd(cmd)
		print(resp)

		print("enumerating settings...")
		settings=dict()
		cmd = Cmd(cmd_type=SETTING_GET_LIST, setting_get_list=CmdSettingGetList(offset=0))
		resp = await ikawa.send_cmd(cmd)
		# print(resp)
		for i in resp.resp_setting_get_list.number:
			cmd = Cmd(cmd_type=SETTING_GET_INFO, setting_get_info=CmdSettingGetInfo(number=i))
			resp = await ikawa.send_cmd(cmd)
			# print(resp)
			settings[resp.resp_setting_get_info.name] = i
		print(f"settings={settings}\n")

		cmd = Cmd(cmd_type=SETTING_GET, setting_get=CmdSettingGet(number=settings['ROASTER_ID']))
		resp = await ikawa.send_cmd(cmd)
		print(resp)

		while True:
			cmd = Cmd(cmd_type=MACH_STATUS_GET_ALL)
			try:
				resp = await ikawa.send_cmd(cmd)
				status = resp.resp_mach_status_get_all
				print(f"{int(time.time())}, {status.time}, {MachState.Name(status.state)}, {status.temp_above*0.1:.1f}, {status.temp_below*0.1:.1f}, {status.setpoint*0.1:.1f}, {status.heater}, {status.fan/255.0:.2f}, {(status.fan_measured/12.0)*60:.0f}")
			except TimeoutError:
				pass
			await asyncio.sleep(0.1)

try:
	asyncio.run(main())
except KeyboardInterrupt:
	print("Received interrupt signal, bye")
