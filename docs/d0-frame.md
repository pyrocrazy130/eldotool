# 0xD0 register read

Verified live on 2026-10-18 against the capture. Every address below matched. This is a read. Opcode 0x0e is not used here.

## Frame

Request, 9 bytes, inside a 0x13 packet. Header byte 1 is 0x80. Sub-command is 0x00. Sub-data is 17 76 04 00. Do discovery first or the answer does not come back.

    D0  0D  00 00  ADDR_LO ADDR_HI  00 00  CHECKSUM

Answer, in the 0x94 poll, not at a fixed offset. Search for D0 8D.

    D0  8D  00 00  ADDR_LO ADDR_HI  VAL_LO VAL_HI  CHECKSUM

Checksum is the low byte of the sum of the first 8 bytes. Value is little-endian. Do not read the byte before the echoed request. That byte is not the value.

## Values on this driver

Address 0x3FD2 reads 1400. It did not move when current, aggregate, or resolution changed. It is not the current.

Per-output current is 0x4000 plus the mA. Confirmed by changing group 1 to 311 and group 2 to 312:

    0x00AA  group 1
    0x00AB  group 2
    0x00AC  group 3
    0x00AD  group 4

Do not write a current without the 0x4000 bit.

Scene levels are two outputs per register. Low byte is the first output of the pair, high byte the second. Confirmed by scene 2 outputs 129 and 130 landing in 0x000C as 81 82.

    0x000A  scene 1, outputs 1 and 2
    0x000B  scene 1, outputs 3 and 4
    0x000C  scene 2, outputs 1 and 2
    0x000D  scene 2, outputs 3 and 4

0x009D low byte is the NTC throttling temperature in degrees C. Confirmed 70 to 73. The high byte stayed 0x19.

0x00A7 low byte is power scaling. Confirmed 255 to 200. The high byte stayed 0x88.

These moved, and each screen change is stored twice. Not written by this tool.

    Start address 1 to 7: 0x0001 high byte, and 0x0002 low byte.
    Group 4 channel mapping 4 to 1, stored as 3 to 0: 0x0052 high byte, and 0x0053 low byte.
    Group 4 scaling on to off, stored as FF to 00: 0x003E high byte, and 0x003F low byte.

Network resolution is stored twice, both bytes 0x30 for 8 bit and 0x20 for 16 bit. Confirmed with interpolation left at Off, which only accounts for 0x0037. The other movement was:

    0x0002 high byte  0x30 to 0x20
    0x0004 low byte   0x30 to 0x20

RDM footprint went from 4 to 8 at the same time. 16-bit mode uses two slots per output. Start address stayed 1.

0x004F low byte is the dimming curve. Confirmed by restoring every other field and leaving the curve at logarithmic. The register went from 0x3700 to 0x3701. Linear is 0. Logarithmic is 1. The high byte stayed 0x37. Soft-linear and square are not known. Do not invent them.

0x0001 low byte is fail mode. Goto Scene 1 is 0x60. Retain last value is 0x20. The high byte stayed 0x01, which is the start address seen in the earlier pass. Goto Scene 2 was 0xA0 in the multi-field pass. That pass also changed resolution and interpolation, so 0xA0 is not proven.

0x0037 low byte is interpolation. White is 0x0C. Off is 0x00. The high byte stayed 0xFF. An earlier note that this byte tracked NTC was wrong. NTC is only the low byte of 0x009D. When the screen said Glow, this byte was 0x0F. That pass also changed resolution, so Glow is not proven by itself. Video and Colour are not known.

## How a name gets attached

1. FluxTool Read, no changes. Write down current per output, curve, minimum level, NTC, startup, fail.
2. Compare those numbers to this table.
3. One field still unnamed: change only that field in FluxTool, read the table again, see which address moved, change it back.
