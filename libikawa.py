import asyncio
from bleak import BleakScanner, BleakClient
from base64 import b64encode, b64decode
from urllib.parse import urlparse
from ikawa_pb2 import *

class Ikawa:
	SERVICE_UUID = 'C92A6046-6C8D-4116-9D1D-D20A8F6A245F'
	WRITE_CHARACTERISTIC_UUID = '851A4582-19C1-4E6C-AB37-E7A03766BA16'
	NOTIFY_CHARACTERISTIC_UUID = '948C5059-7F00-46D9-AC55-BF090AE066E3'

	FRAME_BYTE = 0x7E
	ESCAPE_BYTE = 0x7D
	ESCAPE_MAPPING = {0x7D: 0x5D, 0x7E: 0x5E}
	UNESCAPE_MAPPING = {0x5D: 0x7D, 0x5E: 0x7E}

	def __init__(self):
		self.seq = 1 # start with 1 because seq=0 makes Cmd(cmd_type=BOOTLOADER_GET_VERSION) an empty message which the firmware does not seem to handle
		self.resp_queue = asyncio.Queue()
		self.recv_buf = bytearray()

	async def __aenter__(self):
		await self.scan_and_connect()
		await self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, self.on_notify)
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		await self.client.disconnect()

	async def scan_and_connect(self):
		print(f"Scanning for devices with service UUID: {self.SERVICE_UUID}...")

		def filter_device(device, advertisement_data):
			return self.SERVICE_UUID.lower() in [uuid.lower() for uuid in advertisement_data.service_uuids]

		target_device = await BleakScanner.find_device_by_filter(filter_device, timeout=5)

		if target_device:
			print(f"Found device: {target_device.name} [{target_device.address}] with service UUID: {self.SERVICE_UUID}")
			self.client = BleakClient(target_device, disconnected_callback=self.on_disconnect)
			await self.client.connect()
			if self.client.is_connected:
				print(f"Successfully connected to {target_device.name}")
			else:
				raise RuntimeError("Failed to connect to the device")
		else:
			raise RuntimeError("No device found advertising the specified service UUID")

	async def send_cmd(self, cmd):
		assert isinstance(cmd, Cmd)
		if cmd.seq != 0:
			raise ValueError("Cmd.seq should be left uninitialized and will be auto assigned")
		cmd.seq = self.seq
		data = cmd.SerializeToString()
		frame = self.encode_frame(data)
		await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, frame, response=True)
		resp = await self.resp_queue.get()
		return resp

	def on_disconnect(self, client):
		print(f"Disconnected from {client.address}")

	async def on_notify(self, sender, data):
		# print(f"notify recieved: {data}")
		self.recv_buf += data
		while len(self.recv_buf) and self.recv_buf[0] != self.FRAME_BYTE:
			del self.recv_buf[0]
		if len(self.recv_buf) > 3 and self.recv_buf[-1] == self.FRAME_BYTE:
			try:
				data_decoded = self.decode_frame(self.recv_buf)
				response = Response.FromString(data_decoded)
				if response.seq == self.seq:
					self.seq += 1
					# print(f"response recieved: {response}")
					await self.resp_queue.put(response)
				else:
					print(f"Invalid seq number {response.seq} != {self.seq}, discarding message")
			finally:
				self.recv_buf = bytearray()

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
		data_base64 = urlparse(url).query
		data = b64decode(data_base64)
		roast_profile = RoastProfile.FromString(data)
		return roast_profile
	
	@staticmethod
	def roast_profile_to_url(roast_profile):
		data = roast_profile.SerializeToString()
		data_base64 = b64encode(data)
		url = "https://share.ikawa.support/profile_home/?" + data_base64.decode("utf-8")
		return url
