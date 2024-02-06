# Ikawa Home Roaster Protocol Analysis

This document provides an analysis of the communication protocol used by the Ikawa Home roaster, aimed at enabling platform-independent control, thereby eliminating the need for a mobile app. A potential application of this research is the development of a Linux CLI-based interface for the roaster or similar endeavours.

## Methodology

The analysis was conducted by [decompiling](reverse_engineering) the Ikawa Home Android app and utilizing insights from [esteveespuna's](https://github.com/esteveespuna/IkawaRoasterEmulator) work. Version 2.1.6 of the app was analyzed, as version 2.2.0 introduced obfuscation that complicates reverse engineering efforts. These findings have only been tested on a single roaster unit with firmware version `25.17-g1925d8d-DIRTY`, so the results should be considered preliminary. The findings may in part apply to the Pro variant, but this has not been evaluated.

## Protocol Overview

The communication protocol consists of three layers, each built upon the last:

1. BLE GATT service and characteristics
2. A custom data frame format with CRC checksums
3. Protobuf messages

The protocol operates on a request-response model, where interactions between the app and the roaster involve the app sending a command message and the roaster replying with a response.

## BLE

Communication between the app and the roaster is facilitated over Bluetooth Low Energy (BLE). The roaster advertises a GATT service with UUID `C92A6046-6C8D-4116-9D1D-D20A8F6A245F`, which includes two characteristics:

1. Write characteristic `851A4582-19C1-4E6C-AB37-E7A03766BA16` for sending commands to the roaster.
2. Notify characteristic `948C5059-7F00-46D9-AC55-BF090AE066E3` for receiving responses to commands sent over the write characteristic.

To complete a request-response interaction, a request must be written to the write characteristic, and a listener on the notify characteristic must await the result. Each request and response is tagged with a sequence number to ensure they are correctly matched up.

> [!IMPORTANT]
> The write characteristic only accepts 20 bytes[^1] at a time, so longer data frames need to be split into multiple writes.
> Similarly the notify characteristic provides at most 20 bytes at a time, so a notify may not contain a complete frame and the frame may need to be assembled from multiple notify events.

[^1]: MTU size of 23 - 3 bytes for header

## Frames

Data sent and received are encapsulated in frames, structured as follows:

- Start FRAME_BYTE: `0x7E`
- Escaped payload:
    - Message data
    - Custom CRC16 checksum
- End FRAME_BYTE: `0x7E`

Payload escaping is performed by replacing `0x7E` with `0x7D 0x5E` and `0x7D` with `0x7D 0x5D`. This applies to both the message data and the CRC checksum.

> [!TIP]
> The checksum calculation is based on the original message data before escaping.

### CRC16 checksum algorithm

The following variant of CRC16 is used, where `init_value=0xFFFF`:

```python
def crc16(data, init_value):
    crc = init_value
    for byte in data:
        x = (byte & 255) ^ (crc & 255)
        y = x ^ ((x << 4) & 255)
        crc = ((((crc >> 8) & 255) | ((y << 8) & 65535)) ^ (y >> 4)) ^ ((y << 3) & 65535)
    return int(crc & 65535).to_bytes(2, byteorder='big')
```

## Protobuf

The frames use protobuf messages for encoding data. The primary protobuf messages, `Cmd` and `Response`, include `seq` fields to facilitate the correct matching of requests and responses. These messages optionally contain various other message types depending on the `cmd_type` set. This design allows for a flexible communication scheme capable of supporting a wide range of commands and responses. For a comprehensive list of message types, refer to the [protobuf definition file](ikawa.proto). Most message types are intuitive based on their names.
