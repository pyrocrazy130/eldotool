#!/usr/bin/env python3
"""Replay the 0xD0 register reads from the 2026-10-18 FluxTool capture.

Opcode 0x0d, no new value. Same frames FluxTool sent on Read.
Does not send opcode 0x0e. Does not write.
"""
import ctypes
import ctypes.util
import sys
import time

libusb = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0")
libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
libusb.libusb_init.restype = ctypes.c_int
libusb.libusb_exit.argtypes = [ctypes.c_void_p]
libusb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
libusb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_claim_interface.restype = ctypes.c_int
libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_release_interface.restype = ctypes.c_int
libusb.libusb_close.argtypes = [ctypes.c_void_p]
libusb.libusb_bulk_transfer.argtypes = [
    ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
]
libusb.libusb_bulk_transfer.restype = ctypes.c_int

EP_OUT, EP_IN, N = 0x01, 0x81, 64
# Addresses FluxTool read once the driver was up. Order matches the capture.
ADDRS = [
    0x0000, 0x3FF9, 0x3FF8, 0x3FD2, 0x00AA, 0x00AB, 0x00AC, 0x00AD,
    0x004F, 0x3FE9, 0x0001, 0x0004, 0x0002, 0x0050, 0x003C, 0x0051,
    0x003D, 0x0052, 0x003E, 0x0053, 0x003F, 0x0034, 0x0037, 0x009D,
    0x00A7, 0x000A, 0x000B, 0x000C, 0x000D,
]


def xfer(handle, ep, data):
    buf = ctypes.create_string_buffer(N)
    ctypes.memmove(buf, data, N)
    got = ctypes.c_int(0)
    rc = libusb.libusb_bulk_transfer(handle, ep, buf, N, ctypes.byref(got), 1000)
    if rc != 0:
        return None
    return bytes(buf.raw[:got.value])


def send13(handle, sub, sd, frame):
    pkt = bytearray(N)
    pkt[0] = 0x13
    pkt[1] = 0x80
    pkt[2] = sub
    pkt[3:7] = sd
    pkt[7] = len(frame)
    pkt[8:8 + len(frame)] = frame
    xfer(handle, EP_OUT, bytes(pkt))
    xfer(handle, EP_IN, bytes(N))
    time.sleep(0.02)
    poll = bytearray(N)
    poll[0] = 0x14
    xfer(handle, EP_OUT, bytes(poll))
    xfer(handle, EP_IN, bytes(N))


def read_reg(handle, addr):
    frame = bytearray(9)
    frame[0] = 0xD0
    frame[1] = 0x0D
    frame[4] = addr & 0xFF
    frame[5] = (addr >> 8) & 0xFF
    frame[8] = sum(frame[:8]) & 0xFF
    pkt = bytearray(N)
    pkt[0] = 0x13
    pkt[1] = 0x80
    pkt[3:7] = bytes.fromhex("17760400")
    pkt[7] = 9
    pkt[8:17] = frame
    xfer(handle, EP_OUT, bytes(pkt))
    xfer(handle, EP_IN, bytes(N))  # 0x93 echo
    time.sleep(0.02)
    poll = bytearray(N)
    poll[0] = 0x14
    xfer(handle, EP_OUT, bytes(poll))
    resp = xfer(handle, EP_IN, bytes(N))
    if not resp or resp[0] != 0x94:
        return None
    marker = bytes([0xD0, 0x8D])
    k = resp.find(marker)
    if k < 0 or k + 9 > len(resp):
        return None
    ans = resp[k:k + 9]
    if (sum(ans[:8]) & 0xFF) != ans[8]:
        return None
    if (ans[4] | (ans[5] << 8)) != addr:
        return None
    return ans[6] | (ans[7] << 8)


def main():
    ctx = ctypes.c_void_p()
    if libusb.libusb_init(ctypes.byref(ctx)) != 0:
        return 1
    handle = libusb.libusb_open_device_with_vid_pid(ctx, 0x04D8, 0xFF00)
    if not handle:
        print("TOOLbox not found")
        libusb.libusb_exit(ctx)
        return 1
    if libusb.libusb_claim_interface(handle, 0) != 0:
        print("could not claim interface")
        libusb.libusb_close(handle)
        libusb.libusb_exit(ctx)
        return 1
    # Same discovery FluxTool sends before the register reads.
    send13(handle, 0x09, bytes(4), bytes.fromhex(
        "cc0118ffffffffffff00000000000000000000001000030006f2"))
    send13(handle, 0x09, bytes.fromhex("0fa00400"), bytes.fromhex(
        "cc0124ffffffffffff00000000000000000000001000010c000000000000ffffffffffff0d02"))
    capture = {
        0x0000: 0x130F, 0x3FF9: 0x0001, 0x3FF8: 0x0001, 0x3FD2: 0x0578,
        0x00AA: 0x4136, 0x00AB: 0x4136, 0x00AC: 0x4136, 0x00AD: 0x4136,
        0x004F: 0x3700, 0x3FE9: 0x2520, 0x0001: 0x0160, 0x0004: 0x1630,
        0x0002: 0x3001, 0x0050: 0x0100, 0x003C: 0xFFFF, 0x0051: 0x0201,
        0x003D: 0xFFFF, 0x0052: 0x0302, 0x003E: 0xFFFF, 0x0053: 0x0A03,
        0x003F: 0x00FF, 0x0034: 0xFF04, 0x0037: 0xFF0C, 0x009D: 0x1946,
        0x00A7: 0x88FF, 0x000A: 0xFFFF, 0x000B: 0xFFFF, 0x000C: 0x8080,
        0x000D: 0x8080,
    }
    for addr in ADDRS:
        val = read_reg(handle, addr)
        cap = capture.get(addr)
        if val is None:
            print(f"{addr:04x}   no answer")
            continue
        mark = ""
        if cap is not None and val != cap:
            mark = f"  capture was 0x{cap:04x}"
        elif cap == val:
            mark = "  matches capture"
        print(f"{addr:04x}   0x{val:04x} ({val:5d}){mark}")
    libusb.libusb_release_interface(handle, 0)
    libusb.libusb_close(handle)
    libusb.libusb_exit(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
