# eldoLED TOOLbox pro USB Protocol Analysis

Working notes live in ~/Work/eldotool/docs/protocol.md. This file is the raw 2026-10-18 capture writeup. PID guesses in it are stale. 0x046A was a checksum, not a current.

## Capture
- File: `eldoLED_TOOLbox_capture.pcap`
- Date: 2026-10-18
- Source: DESKTOP-9VARL38 (Windows), Wireshark + USBPcap
- Size: 11,279,876 bytes
- SHA256: fe00e0c4d1bcab2aa23275325ebd4a9c83d3a03eb48b85d6e7ee71abf871c25e
- Packets: 150,515 total
- Link type: 249 (USBPcap custom)

## USB Device
- VID:PID: 04d8:ff00 (Microchip / eldoLED TOOLbox pro)
- Firmware: 18.11 (reg 0x00=0x12=18, reg 0x01=0x0b=11)
- Bulk endpoints: EP 0x01 (OUT), EP 0x81 (IN)
- Transfer size: 64 bytes per bulk transfer

## Protocol Structure

All communication is via 64-byte bulk transfers on endpoints 0x01 (OUT) and 0x81 (IN).

### Command Types

| OUT cmd | IN resp | Description | Count |
|---------|---------|-------------|-------|
| 0x0d    | 0x8d    | Register read (reg number in byte 2) | 17 |
| 0x0e    | 0x8e    | Register write (reg number in byte 2) | 1 |
| 0x0a    | 0x8a    | Unknown (0x0a 00 ff 91 ...) | 1 |
| 0x13    | 0x93    | RDM/DMX search + parameter read | 254 |
| 0x14    | 0x94    | DMX polling / keepalive | 37,235 |

### Register Reads (0x0d / 0x8d)

Format: `0d 00 [reg] 00 [value bytes...]`

| Register | Value | Meaning |
|----------|-------|---------|
| 0x00     | 0x12  | Firmware major (18) |
| 0x01     | 0x0b  | Firmware minor (11) |
| 0x03     | 0x13  | Unknown (19) |
| 0x04     | 0x03  | Unknown (3) - read repeatedly |
| 0x06     | 0xffff | Unknown |
| 0x07     | 0xffff | Unknown |
| 0x08     | 0x01  | Unknown - was written then read |
| 0x27     | 0x014b| Unknown (331) |
| 0x29     | 0x0235| Unknown (565) |

### Register Write (0x0e / 0x8e)

One write observed: reg 0x08 = 0x01

### RDM Search (0x13 / 0x93)

254 RDM search packets. These contain standard ANSI E1.20 RDM
Discovery Unique Branch (DUB) and GET_COMMAND messages.

The driver responded with UID **646F:00136D74** (manufacturer 0x646F).

The RDM packets contain:
- DUB discovery (preamble 0xfe...0xaa 0x55, encoded UID)
- GET_COMMAND messages for parameter reads
- MUTE/UNMUTE commands during discovery

Key RDM data observed in capture:
- UID: 646F:00136D74
- Manufacturer ID: 0x646F (eldoLED)
- Device ID: 0x00136D74

### DMX Polling (0x14 / 0x94)

37,235 pairs of 64-byte DMX polling transfers. These are sent
continuously to keep the toolbox alive and to maintain the DMX
universe. The OUT packet sends a 64-byte DMX frame, and the IN
packet returns the echo/status.

Format: `14 00 00 00 00 00 00 00 ...` (OUT, all zeros = idle DMX)
Response: `94 02 02 60 00 00 00 00 ...` (IN, status + zeros)

## Next Steps for Linux Native Tool

1. **Decode RDM parameters**: The 0x13/0x93 packets contain
   GET_COMMAND RDM messages that read the actual driver parameters
   (DMX address, output current, startup level, etc.). These need
   to be decoded using the ANSI E1.20 RDM protocol specification.

2. **Build libusb-based tool**: Use the USB bridge pattern already
   working in `~/.local/share/wine-fluxtool/bridge/` to send the
   same 64-byte bulk transfers from native Linux code.

3. **Command sequence for Read**:
   a. Open USB device 04d8:ff00
   b. Claim interface 0
   c. Send register reads (0x0d) to identify toolbox firmware
   d. Send RDM DUB discovery (0x13) to find driver UID
   e. Send RDM GET_COMMAND to read each parameter
   f. Decode parameter values from RDM responses

4. **Command sequence for Write** (future, after Read is verified):
   a. Same discovery sequence
   b. Send RDM SET_COMMAND with new parameter value
   c. Verify by reading back
