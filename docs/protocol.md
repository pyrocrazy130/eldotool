# eldoLED TOOLbox pro — native Linux read

Tool: ~/Work/eldotool/eldotool.py

Verified 2026-10-18 on the driver that was on the programming cable.
No Wine. No FluxTool. Read only. Do not add a new SET frame. A SET can change the driver.

## What a run prints

Toolbox firmware 18.11.
Driver UID 646F:00136D74.
DEVICE_INFO: RDM protocol 1.0, model 0x0101, category 0x0509, software 0x0000010F.
DMX footprint 4, personality 1 of 1, start address 1, no sub-devices, 1 sensor.
Sensor 0: temperature, deg C, range -60 to 195, name TNTC.
Model text: LED driver.
Manufacturer text: eldoLED.
Device label: empty (two zero bytes).

That start address is what this one driver reported. It is not a room assignment. Output current is not in this read. An earlier note of 1130 mA was a checksum byte (0x046A) misread as milliamps. Do not use it.

## USB

Device 04d8:ff00. Bulk OUT 0x01, IN 0x81. 64-byte transfers.

Command byte:
  0x0d / 0x8d  register read. Register in byte 2. Value in bytes 4-5 of the IN.
  0x0e / 0x8e  register write. Do not send this from the read tool.
  0x13 / 0x93  RDM. The 0x93 IN is an echo.
  0x14 / 0x94  poll. The real RDM answer is in the second 0x94, not the first.

0x13 header that FluxTool uses, and that the driver answers:
  byte 0 = 0x13
  byte 1 = 0x80   (not an incrementing sequence)
  byte 2 = 0x09
  bytes 3-6 = sub-data (00 00 00 00 on the first discovery, 0F A0 04 00 after)
  byte 7 = RDM frame length
  byte 8+ = RDM frame

## RDM

Discovery, in order:
  1. Un-mute. PID 0x0003, command class 0x10, broadcast, no data. Checksum 0x06F2.
  2. Unique branch. PID 0x0001, command class 0x10, lower 000000000000, upper FFFFFFFFFFFF.
The discovery answer is the E1.20 encoded UID in a 0x94 poll. Decode each pair with AND. Checksum 0x07C1 matched UID 646F:00136D74.

Identity reads are the exact frames FluxTool sent. Command class is 0x20 (SET) with no new value. The driver answers with the current value. Do not invent more of these.

Request PID is at RDM offset 21. The two bytes after the request checksum are the checksum, not a PID. 0x0441, 0x0461, 0x0462, 0x0463, 0x046A were checksums.

Answer inside the second 0x94:
  21  PID_HI  PID_LO  PDL  DATA...
PIDs confirmed live:
  0x0060  DEVICE_INFO          19 bytes, standard E1.20 layout
  0x0200  SENSOR_DEFINITION    sensor number was 0x00 in the request
  0x0080  DEVICE_MODEL_DESCRIPTION   "LED driver"
  0x0081  MANUFACTURER_LABEL         "eldoLED"
  0x0082  DEVICE_LABEL               empty

A normal GET (command class 0x10) for SUPPORTED_PARAMETERS, DMX_START_ADDRESS, and SOFTWARE_VERSION_LABEL got no answer from this driver. Do not switch those to SET just to see if they answer.

## Not decoded yet

FluxTool's Read also sends short frames that start with 0xD0, inside the same 0x13 packet. Those are not E1.20. The single status byte that comes back is not yet mapped to output current or dimming curve. Leave them alone until each address is named from the ft_server binary or another capture where the on-screen value is known.
