import asyncio
import sys
import time
from bleak import BleakScanner, BleakClient, BleakError
from base64 import b64encode, b64decode
from ikawa_pb2 import *

class Ikawa:
	SERVICE_UUID = 'C92A6046-6C8D-4116-9D1D-D20A8F6A245F'
	WRITE_CHARACTERISTIC_UUID = '851A4582-19C1-4E6C-AB37-E7A03766BA16'
	NOTIFY_CHARACTERISTIC_UUID = '948C5059-7F00-46D9-AC55-BF090AE066E3'

	FRAME_BYTE = 0x7E
	ESCAPE_BYTE = 0x7D
	ESCAPE_MAPPING = {0x7D: 0x5D, 0x7E: 0x5E}
	UNESCAPE_MAPPING = {0x5D: 0x7D, 0x5E: 0x7E}

	def __init__(self, reconnect=True, scan_timeout=10, connect_timeout=60, retry_timeout=10, log_level=1, log_target=sys.stdout):
		self.seq = 1 # start with 1 because seq=0 makes Cmd(cmd_type=BOOTLOADER_GET_VERSION) an empty message which the firmware does not seem to handle
		self.resp_queue = asyncio.Queue()
		self.recv_buf = bytearray()
		self.reconnect = True
		self.scan_timeout = scan_timeout
		self.connect_timeout = connect_timeout
		self.retry_timeout = retry_timeout
		self.log_level = log_level
		self.log_target = log_target
		self.log_debug(f"log_level={log_level} log_target={log_target}")

	def log(self, msg):
		if self.log_level >= 1:
			print(f"INFO  {msg}", file=self.log_target)
	
	def log_debug(self, msg):
		if self.log_level >= 2:
			print(f"DEBUG {msg}", file=self.log_target)

	async def __aenter__(self):
		await self.scan()
		await self.connect()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		await self.disconnect()

	async def scan(self):
		self.log(f"Scanning for devices with service UUID: {self.SERVICE_UUID}...")

		def filter_device(device, advertisement_data):
			return self.SERVICE_UUID.lower() in [uuid.lower() for uuid in advertisement_data.service_uuids]

		self.target_device = await BleakScanner.find_device_by_filter(filter_device, timeout=self.scan_timeout)
		if self.target_device:
			self.log(f"Found device: {self.target_device.name} [{self.target_device.address}]")
		else:
			raise RuntimeError("No device found advertising the specified service UUID")

	async def connect(self):
		self.client = BleakClient(self.target_device, disconnected_callback=self.on_disconnect)
		t = time.time()
		while time.time() - t < self.connect_timeout:
			self.log("Trying to connect")
			try:
				await self.client.connect()
				break
			except (BleakError, TimeoutError):
				pass
			await asyncio.sleep(0.1)
		if not self.client.is_connected:
			raise RuntimeError("Failed to connect to the device, maximum retries exceeded")
		self.log(f"Connected to {self.target_device.name}")
		await self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, self.on_notify)

	async def disconnect(self):
		reconnect = self.reconnect
		self.reconnect = False
		await self.client.disconnect()
		self.reconnect = reconnect

	async def send_frame(self, frame):
		success=False
		t = time.time()
		while time.time() - t < self.retry_timeout:
			self.log_debug("trying to send frame")
			try:
				await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, frame, response=True)
				success=True
				break
			except BleakError as e:
				pass
			await asyncio.sleep(0.1)
		if not success:
			raise RuntimeError("Device is disconnected, maximum retries exceeded")
		self.log_debug(f"send data frame {frame}")

	def on_disconnect(self, client):
		self.log(f"Disconnected from {client.address}")
		if self.reconnect:
			asyncio.get_running_loop().create_task(self.connect())

	async def on_notify(self, sender, data):
		self.log_debug(f"notify recieved: (len={len(data)}) {data}")
		self.recv_buf += data
		while True:
			try:
				frame_start = self.recv_buf.index(self.FRAME_BYTE)
				frame_end = frame_start + self.recv_buf[frame_start+1:].index(self.FRAME_BYTE) + 1
			except ValueError:
				# no more complete frames, wait for more data
				break
			frame = self.recv_buf[frame_start:frame_end+1]
			self.log_debug(f"detected frame {frame}")
			del self.recv_buf[:frame_end]
			if len(frame) < 3:
				self.log_debug("accidentally considered end of previous frame as start of next, discarding")
				continue
			del self.recv_buf[0]
			data_decoded = self.decode_frame(frame)
			response = Response.FromString(data_decoded)
			if response.seq == self.seq:
				self.seq += 1
				self.log_debug(f"response recieved: {response}")
				await self.resp_queue.put(response)
			else:
				self.log(f"Invalid seq number {response.seq} != {self.seq}, discarding message")

	async def send_cmd(self, cmd):
		assert isinstance(cmd, Cmd)
		if cmd.seq != 0:
			raise ValueError("cmd.seq should be left uninitialized and will be auto assigned")
		cmd.seq = self.seq
		data = cmd.SerializeToString()
		cmd.seq = 0
		frame = self.encode_frame(data)
		for i in range(0, len(frame), 20):
			frame_part = frame[i:i+20]
			self.log_debug(f"sending (len={len(frame_part)}) {frame_part}")
			await self.send_frame(frame_part)
		self.log_debug("waiting for response")
		resp = await asyncio.wait_for(self.resp_queue.get(), self.retry_timeout)
		return resp

	@classmethod
	def encode_frame(cls, data):
		# Calculate CRC on the original data
		crc = cls.crc16(data, 0xFFFF) # Assuming crc16 works with init_value=0xFFFF

		# Function to escape data including CRC
		def escape_data(input_data):
			escaped_data = bytearray()
			for byte in input_data:
				if byte in cls.ESCAPE_MAPPING:
					escaped_data.append(cls.ESCAPE_BYTE)
					escaped_data.append(cls.ESCAPE_MAPPING[byte])
				else:
					escaped_data.append(byte)
			return escaped_data

		escaped_data = escape_data(data)
		escaped_crc = escape_data(crc)

		# Frame the data
		framed_data = bytearray([cls.FRAME_BYTE]) + escaped_data + escaped_crc + bytearray([cls.FRAME_BYTE])
		return framed_data

	@classmethod
	def decode_frame(cls, framed_data):
		if framed_data[0] != cls.FRAME_BYTE or framed_data[-1] != cls.FRAME_BYTE:
			raise ValueError("Invalid frame format")

		# Remove frame bytes
		data_with_crc_escaped = framed_data[1:-1]

		# Function to unescape data
		def unescape_data(input_data):
			unescaped_data = bytearray()
			iterator = iter(input_data)
			for byte in iterator:
				if byte == cls.ESCAPE_BYTE:
					next_byte = next(iterator, None)
					unescaped_data.append(cls.UNESCAPE_MAPPING[next_byte])
				else:
					unescaped_data.append(byte)
			return unescaped_data

		data_with_crc = unescape_data(data_with_crc_escaped)

		# Separate data and CRC
		data = data_with_crc[:-2]
		received_crc = data_with_crc[-2:]

		# Validate CRC
		calculated_crc = cls.crc16(data, 0xFFFF) # Recalculate CRC on unescaped data
		if received_crc != calculated_crc:
			raise ValueError("CRC check failed")

		return data

	@staticmethod
	def crc16(data, init_value):
		crc = init_value
		for byte in data:
			x = (byte & 255) ^ (crc & 255)
			y = x ^ ((x << 4) & 255)
			crc = ((((crc >> 8) & 255) | ((y << 8) & 65535)) ^ (y >> 4)) ^ ((y << 3) & 65535)
		return int(crc & 65535).to_bytes(2, byteorder='big')

	@staticmethod
	def roast_profile_from_url(url):
		try:
			index = url.rindex("?")
			data_base64 = url[index+1:]
		except ValueError:
			data_base64 = url
		data = b64decode(data_base64)
		roast_profile = RoastProfile.FromString(data)
		return roast_profile
	
	@staticmethod
	def roast_profile_to_url(roast_profile):
		data = roast_profile.SerializeToString()
		data_base64 = b64encode(data)
		url = "https://share.ikawa.support/profile_home/?" + data_base64.decode("utf-8")
		return url
