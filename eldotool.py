#!/usr/bin/env python3
"""
eldoLED TOOLbox pro native Linux Read tool.

Talks directly to the TOOLbox dongle (VID 04d8, PID ff00) via libusb-1.0.
Sends 64-byte bulk transfers that match FluxTool's protocol.

Protocol summary:
  - 0x0d/0x8d: Register read (reg in byte 2, value in bytes 4-5)
  - 0x0e/0x8e: Register write
  - 0x13/0x93: RDM command (0x93 is just an echo; actual response is async)
  - 0x14/0x94: DMX poll (0x94 IN carries the async RDM response data)

RDM response data is in a later 0x94 poll, as 21 PID_HI PID_LO PDL DATA.
The 0x93 packet is only an echo. Do not treat the bytes after an RDM
request checksum as a PID.

Usage:
    python3 eldotool.py            # Read all parameters from connected driver
    python3 eldotool.py --debug     # Verbose packet logging
"""
import ctypes
import ctypes.util
import struct
import sys
import time

# --- libusb ctypes bindings (minimal) ---
libusb = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0")

libusb.libusb_init = libusb.libusb_init
libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
libusb.libusb_init.restype = ctypes.c_int

libusb.libusb_exit = libusb.libusb_exit
libusb.libusb_exit.argtypes = [ctypes.c_void_p]
libusb.libusb_exit.restype = None

libusb.libusb_open_device_with_vid_pid = libusb.libusb_open_device_with_vid_pid
libusb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
libusb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p

libusb.libusb_claim_interface = libusb.libusb_claim_interface
libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_claim_interface.restype = ctypes.c_int

libusb.libusb_release_interface = libusb.libusb_release_interface
libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_release_interface.restype = ctypes.c_int

libusb.libusb_close = libusb.libusb_close
libusb.libusb_close.argtypes = [ctypes.c_void_p]
libusb.libusb_close.restype = None

libusb.libusb_bulk_transfer = libusb.libusb_bulk_transfer
libusb.libusb_bulk_transfer.argtypes = [
    ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
]
libusb.libusb_bulk_transfer.restype = ctypes.c_int

VID = 0x04D8
PID = 0xFF00
EP_OUT = 0x01
EP_IN = 0x81
TIMEOUT_MS = 2000
BULK_SIZE = 64

# Known driver UID from capture (eldoLED POWERdrive 50U-M4Z0X)
DRIVER_UID = bytes.fromhex('646f00136d74')
TOOLBOX_UID = bytes.fromhex('646f00000042')


def bulk_write(handle, data, debug=False):
    buf = ctypes.create_string_buffer(BULK_SIZE)
    ctypes.memmove(buf, data, min(len(data), BULK_SIZE))
    transferred = ctypes.c_int(0)
    rc = libusb.libusb_bulk_transfer(handle, EP_OUT, buf, BULK_SIZE,
                                      ctypes.byref(transferred), TIMEOUT_MS)
    if debug:
        print(f"  OUT rc={rc} xfer={transferred.value}")
        print(f"      {' '.join(f'{b:02x}' for b in data[:24])}")
    if rc != 0:
        raise RuntimeError(f"bulk_write failed rc={rc}")
    return transferred.value


def bulk_read(handle, debug=False):
    buf = ctypes.create_string_buffer(BULK_SIZE)
    transferred = ctypes.c_int(0)
    rc = libusb.libusb_bulk_transfer(handle, EP_IN, buf, BULK_SIZE,
                                     ctypes.byref(transferred), TIMEOUT_MS)
    if debug:
        print(f"  IN  rc={rc} xfer={transferred.value}")
    if rc != 0:
        return None, rc
    return bytes(buf.raw[:transferred.value]), 0


def reg_read(handle, reg, debug=False):
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x0d
    pkt[2] = reg
    bulk_write(handle, bytes(pkt), debug)
    resp, rc = bulk_read(handle, debug)
    if resp is None:
        return None
    return (resp[3] << 8) | resp[4] if len(resp) >= 5 else None


def dmx_poll(handle, debug=False):
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x14
    bulk_write(handle, bytes(pkt), debug)
    resp, rc = bulk_read(handle, debug)
    return resp


def rdm_command(handle, seq, sub_cmd, sub_data, rdm_frame, debug=False, polls=3):
    """Send an RDM frame via 0x13. The real answer is in a later 0x94 poll, not the 0x93 echo."""
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x13
    pkt[1] = 0x80
    pkt[2] = sub_cmd
    for i, b in enumerate(sub_data[:4]):
        pkt[3 + i] = b
    pkt[7] = len(rdm_frame)
    for i, b in enumerate(rdm_frame):
        if 8 + i < BULK_SIZE:
            pkt[8 + i] = b
    bulk_write(handle, bytes(pkt), debug)
    echo, rc = bulk_read(handle, debug)
    found = []
    for _ in range(polls):
        time.sleep(0.02)
        resp = dmx_poll(handle, debug)
        if resp:
            found.append(resp)
            if extract_set_response(resp):
                break
    return found


def build_rdm(dest, src, cmd_class, pid, data=b''):
    """E1.20 frame. Checksum is the sum of the message, big-endian."""
    pdl = len(data)
    ml = 24 + pdl
    frame = bytearray(ml + 2)
    frame[0] = 0xCC
    frame[1] = 0x01
    frame[2] = ml
    frame[3:9] = dest
    frame[9:15] = src
    frame[16] = 0x01
    frame[20] = cmd_class
    frame[21] = (pid >> 8) & 0xFF
    frame[22] = pid & 0xFF
    frame[23] = pdl
    frame[24:24 + pdl] = data
    csum = sum(frame[:ml]) & 0xFFFF
    frame[ml] = (csum >> 8) & 0xFF
    frame[ml + 1] = csum & 0xFF
    return bytes(frame)


def extract_any_response(pkt):
    """Find a 0x11 GET response or 0x21 SET response in a poll."""
    if not pkt:
        return None
    for i in range(0, len(pkt) - 4):
        if pkt[i] not in (0x11, 0x21):
            continue
        pid = (pkt[i + 1] << 8) | pkt[i + 2]
        pdl = pkt[i + 3]
        end = i + 4 + pdl
        if pdl > 40 or end > len(pkt):
            continue
        if pid == 0:
            continue
        return {'cc': pkt[i], 'pid': pid, 'data': bytes(pkt[i + 4:end])}
    return None


def extract_set_response(pkt):
    """Parameter answer inside a 0x94 poll: 21 PID_HI PID_LO PDL DATA."""
    if not pkt:
        return None
    for i in range(0, len(pkt) - 4):
        if pkt[i] != 0x21:
            continue
        pid = (pkt[i + 1] << 8) | pkt[i + 2]
        pdl = pkt[i + 3]
        end = i + 4 + pdl
        if pdl > 32 or end > len(pkt):
            continue
        if pid not in (0x0060, 0x0080, 0x0081, 0x0082, 0x0200, 0x00F0, 0x0050):
            continue
        return {'pid': pid, 'data': bytes(pkt[i + 4:end])}
    return None


def decode_discovery(pkt):
    """E1.20 discovery response: each UID/checksum byte is sent as (b|0xAA, b|0x55)."""
    if not pkt:
        return None
    for i in range(0, len(pkt) - 16):
        chunk = pkt[i:i + 16]
        if chunk[0] not in (0xEE, 0xFE, 0xEF):
            continue
        decoded = bytes(chunk[j] & chunk[j + 1] for j in range(0, 16, 2))
        uid, csum = decoded[:6], decoded[6:8]
        if uid[:2] != bytes.fromhex('646f'):
            continue
        return uid, csum
    return None


def make_rdm_frame(dest_uid, src_uid, pid, data=b'', cmd_class=0x00):
    frame = bytearray(26)
    frame[0] = 0xCC
    frame[1] = 0x01
    frame[2] = 24 + len(data)
    frame[3:9] = dest_uid
    frame[9:15] = src_uid
    frame[15] = cmd_class
    frame[16] = 0x00  # response type
    frame[17] = 0x00  # message count
    frame[18] = len(data)
    frame[19] = (pid >> 8) & 0xFF
    frame[20] = pid & 0xFF
    for i, b in enumerate(data):
        if 21 + i < 26:
            frame[21 + i] = b
    return bytes(frame)


def decode_rdm_response(resp):
    """Decode RDM data from a 0x94 response packet."""
    if resp is None or len(resp) < 10:
        return None
    if not any(resp[4:30]):
        return None

    # DUB response (encoded UID)
    if resp[4] in (0xee, 0xfe, 0xef):
        return {'type': 'dub', 'raw': resp[4:24].hex()}

    # Standard RDM frame at offset 8
    if len(resp) > 8 and resp[8] == 0xCC:
        rdm = resp[8:]
        if len(rdm) >= 21:
            dest = rdm[3:9]
            src = rdm[9:15]
            data_len = rdm[18]
            pid = (rdm[19] << 8) | rdm[20]
            data = rdm[21:21+data_len] if data_len > 0 else b''
            return {
                'type': 'get_response',
                'dest': dest.hex(':'),
                'src': src.hex(':'),
                'pid': pid,
                'data': data,
            }

    return {'type': 'raw', 'raw': resp[4:32].hex()}


# RDM PID names
PID_NAMES = {
    0x0010: 'DISC_UNIQUE_BRANCH',
    0x0020: 'DEVICE_INFO',
    0x0030: 'DEVICE_LABEL',
    0x0040: 'DMX_START_ADDRESS',
    0x0461: 'OUTPUT_CURRENT',
    0x0462: 'DMX_CURVE',
    0x0463: 'STARTUP_LEVEL',
}


def main():
    debug = '--debug' in sys.argv

    ctx = ctypes.c_void_p()
    rc = libusb.libusb_init(ctypes.byref(ctx))
    if rc != 0:
        print(f"libusb_init failed: {rc}")
        return 1

    print(f"Opening TOOLbox pro (VID {VID:04x} PID {PID:04x})...")
    handle = libusb.libusb_open_device_with_vid_pid(ctx, VID, PID)
    if not handle:
        print("TOOLbox not found. Is it plugged in?")
        libusb.libusb_exit(ctx)
        return 1

    rc = libusb.libusb_claim_interface(handle, 0)
    if rc != 0:
        print(f"claim_interface failed: {rc}")
        libusb.libusb_close(handle)
        libusb.libusb_exit(ctx)
        return 1

    print("TOOLbox connected.\n")

    # Step 1: Read toolbox registers
    print("=== Toolbox registers ===")
    fw_major = reg_read(handle, 0x00, debug)
    fw_minor = reg_read(handle, 0x01, debug)
    print(f"  Firmware: {fw_major}.{fw_minor}")

    # Step 2: RDM discovery. DUB1 is unmute (PID 0x0003). DUB2 is unique-branch.
    print("\n=== RDM discovery ===")
    seq = 0
    dub1 = bytes.fromhex('cc0118ffffffffffff00000000000000000000001000030006f2')
    rdm_command(handle, seq, 0x09, bytes(4), dub1, debug, polls=1)
    seq += 1
    dub2 = bytes.fromhex('cc0124ffffffffffff00000000000000000000001000010c000000000000ffffffffffff0d02')
    polls = rdm_command(handle, seq, 0x09, bytes.fromhex('0fa00400'), dub2, debug, polls=3)
    seq += 1
    uid = None
    for pkt in polls:
        found = decode_discovery(pkt)
        if found:
            uid, csum = found
            print(f"  Driver UID: {uid[:2].hex()}:{uid[2:].hex()}  checksum {csum.hex()}")
            break
    if uid is None:
        print("  No discovery response. Is the programming cable on the driver DMX input?")
        uid = DRIVER_UID
        print(f"  Falling back to captured UID {uid[:2].hex()}:{uid[2:].hex()}")

    # Step 3: replay the exact FluxTool identity reads. These are SET-class
    # frames with no parameter data; the driver answers with the current value.
    # Do not add new SET frames here. A GET is safe; a SET can change the driver.
    print("\n=== Driver identity ===")
    reads = [
        ('DEVICE_INFO', bytes.fromhex('cc0118646f00136d74646f000000420000000000200060000441')),
        ('SENSOR_0', bytes.fromhex('cc0119646f00136d74646f000000420000000000200200010003e5')),
        ('MODEL', bytes.fromhex('cc0118646f00136d74646f000000420000000000200080000461')),
        ('MANUFACTURER', bytes.fromhex('cc0118646f00136d74646f000000420000000000200081000462')),
        ('LABEL', bytes.fromhex('cc0118646f00136d74646f000000420000000000200082000463')),
    ]
    # Retarget the captured frames at the UID we just found, and fix the checksum.
    def retarget(frame, dest):
        frame = bytearray(frame)
        frame[3:9] = dest
        ml = frame[2]
        csum = sum(frame[:ml]) & 0xFFFF
        frame[ml] = (csum >> 8) & 0xFF
        frame[ml + 1] = csum & 0xFF
        return bytes(frame)

    for name, frame in reads:
        frame = retarget(frame, uid)
        polls = rdm_command(handle, seq, 0x09, bytes.fromhex('0fa00400'), frame, debug)
        seq = (seq + 1) & 0x7F
        parsed = None
        for pkt in polls:
            parsed = extract_set_response(pkt)
            if parsed:
                break
        if not parsed:
            blobs = []
            for pkt in polls:
                if any(pkt[4:32]):
                    blobs.append(pkt[4:36].hex())
            print(f"  {name}: no answer" + (f"  raw={blobs}" if blobs else ""))
            continue
        data = parsed['data']
        print_param(name, parsed['pid'], data)

    libusb.libusb_release_interface(handle, 0)
    libusb.libusb_close(handle)
    libusb.libusb_exit(ctx)
    print("\nDone.")


def print_param(name, pid, data):
    ascii_s = ''.join(chr(b) if 32 <= b < 127 else '' for b in data).strip()
    if pid == 0x0060 and len(data) >= 19:
        model = (data[2] << 8) | data[3]
        category = (data[4] << 8) | data[5]
        sw = int.from_bytes(data[6:10], 'big')
        footprint = (data[10] << 8) | data[11]
        start = (data[14] << 8) | data[15]
        print(f"  {name}: protocol {data[0]}.{data[1]}, model {model:#06x}, "
              f"category {category:#06x}, software {sw:#010x}")
        print(f"    DMX footprint {footprint}, personality {data[12]} of {data[13]}, "
              f"start address {start}, sub-devices { (data[16]<<8)|data[17] }, sensors {data[18]}")
        return
    if pid == 0x0200 and len(data) >= 13:
        smin = int.from_bytes(data[4:6], 'big', signed=True)
        smax = int.from_bytes(data[6:8], 'big', signed=True)
        desc = data[13:].decode('ascii', 'replace')
        print(f"  {name}: sensor {data[0]} type {data[1]} unit {data[2]} "
              f"range {smin}..{smax}  {desc!r}")
        return
    if ascii_s:
        print(f"  {name}: {ascii_s!r}")
        return
    print(f"  {name}: pid {pid:#06x} data {data.hex(' ') or '(empty)'}")


if __name__ == "__main__":
    sys.exit(main())
