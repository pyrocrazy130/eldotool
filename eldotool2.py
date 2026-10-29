#!/usr/bin/env python3
"""
eldoLED TOOLbox pro — Linux read/write tool.

Talks directly to the TOOLbox dongle (VID 04d8 PID ff00) via libusb-1.0.
No Wine, no FluxTool, no ft_server.

Read:  Standard RDM SET (0x20, PDL=0) for identity PIDs
       0xD0 extended register read for config parameters
Write: 0xD0 extended register write (opcode 0x0E)
       Changes the stored register value. May need a driver power cycle
       to take effect on the running DMX output.
DMX:   Chunked 0x13 frames, same path as FluxTool dmx.send.
       Levels hold only while frames are refreshed. When they stop,
       the driver falls back to its fail mode.

Usage:
    python3 eldotool2.py                    # Read all parameters
    python3 eldotool2.py --read             # Read only (safe, no writes)
    python3 eldotool2.py --write PID VALUE  # Write a parameter
    python3 eldotool2.py --dmx 1=128,2=64 --seconds 4
    python3 eldotool2.py --interactive      # Interactive menu
    python3 eldotool2.py --debug            # Verbose packet logging
"""
import ctypes
import ctypes.util
import struct
import sys
import time
import os

# ─── Rich dark theme ──────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich.theme import Theme

    dark_theme = Theme({
        "header": "bold cyan",
        "label": "bold white",
        "value": "green",
        "warn": "bold yellow",
        "error": "bold red",
        "ok": "bold green",
        "dim": "dim",
        "param": "cyan",
        "addr": "dim yellow",
    })
    console = Console(theme=dark_theme, force_terminal=True)
except ImportError:
    console = None

# ─── libusb ───────────────────────────────────────────────────────────
libusb = ctypes.CDLL(ctypes.util.find_library("usb-1.0") or "libusb-1.0")
libusb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
libusb.libusb_init.restype = ctypes.c_int
libusb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
libusb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
libusb.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
libusb.libusb_close.argtypes = [ctypes.c_void_p]
libusb.libusb_exit.argtypes = [ctypes.c_void_p]
libusb.libusb_bulk_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p,
                                        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
libusb.libusb_bulk_transfer.restype = ctypes.c_int

VID, PID = 0x04D8, 0xFF00
EP_OUT, EP_IN = 0x01, 0x81
BULK_SIZE = 64
TIMEOUT_MS = 2000
DRIVER_UID = bytes.fromhex('646f00136d74')
TOOLBOX_UID = bytes.fromhex('646f00000042')


# ─── Parameter map (from d0-frame.md + FluxTool analysis) ─────────────
# Each entry: (name, d0_addr, description, value_map_or_None)
PARAM_MAP = [
    ("dmx_start_address", 0x0002, "Network start address", None),
    ("fail_mode", 0x0001, "Fail mode", {0x60: "Goto Scene 1", 0x20: "Retain last value"}),
    ("interpolation", 0x0037, "Interpolation", {0x00: "Off", 0x0C: "White"}),
    ("dimming_curve", 0x004F, "Dimming curve", {0x00: "Linear", 0x01: "Logarithmic"}),
    ("ntc_throttling_temp", 0x009D, "NTC throttling temperature", None),
    ("power_scaling", 0x00A7, "Power scaling", None),
    ("current_cs1", 0x00AA, "Output current channel 1", None),
    ("current_cs2", 0x00AB, "Output current channel 2", None),
    ("current_cs3", 0x00AC, "Output current channel 3", None),
    ("current_cs4", 0x00AD, "Output current channel 4", None),
    ("scene1_out12", 0x000A, "Scene 1 outputs 1 and 2", None),
    ("scene1_out34", 0x000B, "Scene 1 outputs 3 and 4", None),
    ("scene2_out12", 0x000C, "Scene 2 outputs 1 and 2", None),
    ("scene2_out34", 0x000D, "Scene 2 outputs 3 and 4", None),
    ("group4_scaling", 0x003F, "Group 4 scaling", {0x00: "Off", 0xFF: "On"}),
    ("group4_mapping", 0x0053, "Group 4 channel mapping", None),
    ("network_resolution", 0x0002, "Network resolution", {0x30: "8-bit", 0x20: "16-bit"}),
]

# PIDs for identity reads (SET with no data → driver returns current value)
IDENTITY_PIDS = [
    ('DEVICE_INFO', 0x0060),
    ('SENSOR_0', 0x0200),
    ('MODEL', 0x0080),
    ('MANUFACTURER', 0x0081),
    ('LABEL', 0x0082),
]

# Discovery frames (from captured FluxTool traffic)
DUB1 = bytes.fromhex('cc0118ffffffffffff00000000000000000000001000030006f2')
DUB2 = bytes.fromhex('cc0124ffffffffffff00000000000000000000001000010c000000000000ffffffffffff0d02')


# ─── USB helpers ──────────────────────────────────────────────────────
def bulk_write(handle, data, debug=False):
    buf = ctypes.create_string_buffer(BULK_SIZE)
    ctypes.memmove(buf, data, min(len(data), BULK_SIZE))
    xfer = ctypes.c_int(0)
    rc = libusb.libusb_bulk_transfer(handle, EP_OUT, buf, BULK_SIZE, ctypes.byref(xfer), TIMEOUT_MS)
    if debug:
        print(f"  OUT rc={rc} xfer={xfer.value} {' '.join(f'{b:02x}' for b in data[:24])}")
    if rc != 0:
        raise RuntimeError(f"bulk_write failed rc={rc}")


def bulk_read(handle, debug=False):
    buf = ctypes.create_string_buffer(BULK_SIZE)
    xfer = ctypes.c_int(0)
    rc = libusb.libusb_bulk_transfer(handle, EP_IN, buf, BULK_SIZE, ctypes.byref(xfer), TIMEOUT_MS)
    if debug:
        print(f"  IN  rc={rc} xfer={xfer.value}")
    if rc != 0:
        return None
    return bytes(buf.raw[:xfer.value])


def dmx_poll(handle, debug=False):
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x14
    bulk_write(handle, bytes(pkt), debug)
    return bulk_read(handle, debug)


def reg_read(handle, reg, debug=False):
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x0d
    pkt[2] = reg
    bulk_write(handle, bytes(pkt), debug)
    resp, rc = bulk_read(handle, debug), 0
    if resp is None:
        return None
    return (resp[3] << 8) | resp[4] if len(resp) >= 5 else None


# ─── RDM ──────────────────────────────────────────────────────────────
def rdm_send(handle, rdm_frame, sub_data=bytes.fromhex('0fa00400'), polls=5, debug=False):
    """Send RDM frame via 0x13, collect poll responses."""
    pkt = bytearray(BULK_SIZE)
    pkt[0] = 0x13
    pkt[1] = 0x80
    pkt[2] = 0x09
    for i, b in enumerate(sub_data[:4]):
        pkt[3 + i] = b
    pkt[7] = len(rdm_frame)
    for i, b in enumerate(rdm_frame):
        if 8 + i < BULK_SIZE:
            pkt[8 + i] = b
    bulk_write(handle, bytes(pkt), debug)
    echo = bulk_read(handle, debug)  # 0x93 echo
    responses = []
    for _ in range(polls):
        time.sleep(0.04)
        resp = dmx_poll(handle, debug)
        if resp and any(resp[4:40]):
            responses.append(resp)
    return responses


def parse_dmx_levels(spec):
    """Parse '1=128,2=64' into {channel: value}. Channels are 1-512."""
    levels = {}
    if not spec or not spec.strip():
        return levels
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            raise ValueError(f"expected CH=VAL, got {part!r}")
        ch_s, val_s = part.split('=', 1)
        ch = int(ch_s, 0)
        val = int(val_s, 0)
        if not 1 <= ch <= 512:
            raise ValueError(f"channel {ch} out of range 1-512")
        if not 0 <= val <= 255:
            raise ValueError(f"value {val} out of range 0-255")
        levels[ch] = val
    return levels


def build_protocol_packets(payload, break_byte=0, answer_timeout=0, flags=0):
    """Chunk a protocol payload the way ft_server's DMX send path does.

    First 0x13 packet carries up to 56 bytes at offset 8.
    Continuation 0x13 packets carry up to 60 bytes at offset 4.
    Byte 1 of the first packet is (continuation count | 0x80).
    This is the wire format behind FluxTool dmx.send. Break byte 0
    matches captured frames when break_time is left at the default.
    """
    payload = bytes(payload)
    n = len(payload)
    if n > 600:
        raise ValueError(f"payload {n} bytes is longer than the chunker allows")
    if n <= 0x38:
        first_len = n
        n_cont = 0
    else:
        first_len = 0x38
        n_cont = (n - 0x38) // 0x3c + 1
    packets = []
    first = bytearray(BULK_SIZE)
    first[0] = 0x13
    first[1] = (n_cont | 0x80) & 0xFF
    first[2] = break_byte & 0xFF
    first[3] = (answer_timeout >> 8) & 0xFF
    first[4] = answer_timeout & 0xFF
    first[5] = flags & 0xFF
    first[6] = 0
    first[7] = first_len
    first[8:8 + first_len] = payload[:first_len]
    packets.append(bytes(first))
    offset = first_len
    for i in range(n_cont):
        chunk = payload[offset:offset + 0x3c]
        offset += len(chunk)
        cont = bytearray(BULK_SIZE)
        cont[0] = 0x13
        cont[1] = i + 1
        cont[2] = 0
        cont[3] = len(chunk)
        cont[4:4 + len(chunk)] = chunk
        packets.append(bytes(cont))
    return packets


def send_protocol(handle, payload, debug=False, break_byte=0, flags=0):
    """Send one protocol payload. Returns the 0x93 echo of each chunk."""
    echoes = []
    for pkt in build_protocol_packets(payload, break_byte=break_byte, flags=flags):
        bulk_write(handle, pkt, debug)
        echoes.append(bulk_read(handle, debug))
    return echoes


def send_dmx_levels(handle, levels, seconds=3.0, start_code=0, debug=False, hz=25):
    """Stream a DMX frame for `seconds`. levels is {channel: 0-255}.

    Channel 1 is byte 1. Byte 0 is the start code (0x00 for normal DMX).
    The dongle only holds the level while frames keep coming.
    """
    frame = bytearray(513)
    frame[0] = start_code & 0xFF
    for ch, val in levels.items():
        frame[ch] = val & 0xFF
    period = 1.0 / hz if hz else 0.04
    deadline = time.time() + max(0.0, seconds)
    sent = 0
    first_echo = None
    while True:
        echoes = send_protocol(handle, frame, debug=(debug and sent == 0))
        if first_echo is None:
            first_echo = echoes[0] if echoes else None
        sent += 1
        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(period, deadline - now))
    return sent, first_echo, bytes(frame)


def build_rdm(dest, src, cmd_class, pid, data=b''):
    """Build an E1.20 RDM frame."""
    pdl = len(data)
    ml = 24 + pdl
    frame = bytearray(ml + 2)
    frame[0] = 0xCC
    frame[1] = 0x01
    frame[2] = ml
    frame[3:9] = dest
    frame[9:15] = src
    frame[15] = 0x00  # PORT_ID
    frame[16] = 0x00  # MESSAGE_COUNT
    frame[20] = cmd_class
    frame[21] = (pid >> 8) & 0xFF
    frame[22] = pid & 0xFF
    frame[23] = pdl
    frame[24:24 + pdl] = data
    csum = sum(frame[:ml]) & 0xFFFF
    frame[ml] = (csum >> 8) & 0xFF
    frame[ml + 1] = csum & 0xFF
    return bytes(frame)


def find_set_response(responses, expected_pid=None):
    """Find 0x21 SET response in poll data."""
    for resp in responses:
        data = resp[4:48]
        for i in range(len(data) - 4):
            if data[i] == 0x21:
                pid = (data[i + 1] << 8) | data[i + 2]
                pdl = data[i + 3]
                if pdl < 32 and i + 4 + pdl <= len(data):
                    if expected_pid is None or pid == expected_pid:
                        return {'pid': pid, 'pdl': pdl, 'data': bytes(data[i + 4:i + 4 + pdl])}
    return None


def decode_discovery(pkt):
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


# ─── 0xD0 extended register read/write ────────────────────────────────
def build_d0_frame(opcode, addr, val_lo=0, val_hi=0):
    """Build a 0xD0 extended register frame (9 bytes, inside 0x13 packet).
    Read:  opcode=0x0D   Write: opcode=0x0E
    Checksum = low byte of sum of first 8 bytes."""
    frame = bytearray(9)
    frame[0] = 0xD0
    frame[1] = opcode
    frame[4] = addr & 0xFF        # ADDR_LO
    frame[5] = (addr >> 8) & 0xFF  # ADDR_HI
    frame[6] = val_lo             # VAL_LO
    frame[7] = val_hi             # VAL_HI
    frame[8] = sum(frame[:8]) & 0xFF
    return bytes(frame)


def d0_read(handle, addr, debug=False):
    """Read a 0xD0 extended register. Returns (val_lo, val_hi) or None."""
    frame = build_d0_frame(0x0D, addr)
    responses = rdm_send(handle, frame, polls=4, debug=debug)
    for resp in responses:
        data = resp[4:48]
        for i in range(len(data) - 8):
            if data[i] == 0xD0 and data[i + 1] == 0x8D:
                addr_lo = data[i + 4]
                addr_hi = data[i + 5]
                val_lo = data[i + 6]
                val_hi = data[i + 7]
                if (addr_hi << 8 | addr_lo) == addr:
                    return val_lo, val_hi
    return None


def d0_write(handle, addr, val_lo, val_hi=0, debug=False):
    """Write a 0xD0 extended register. Returns True if write ACK received."""
    frame = build_d0_frame(0x0E, addr, val_lo, val_hi)
    responses = rdm_send(handle, frame, polls=6, debug=debug)
    for resp in responses:
        data = resp[4:48]
        for i in range(len(data) - 8):
            if data[i] == 0xD0 and data[i + 1] == 0x8E:
                addr_lo = data[i + 4]
                addr_hi = data[i + 5]
                resp_lo = data[i + 6]
                if (addr_hi << 8 | addr_lo) == addr and resp_lo == val_lo:
                    return True
    return False


# ─── High-level parameter operations ────────────────────────────────
def discover_driver(handle, debug=False):
    """Run RDM discovery, return driver UID."""
    rdm_send(handle, DUB1, bytes(4), polls=1, debug=debug)
    polls = rdm_send(handle, DUB2, bytes.fromhex('0fa00400'), polls=3, debug=debug)
    for pkt in polls:
        found = decode_discovery(pkt)
        if found:
            uid, csum = found
            return uid
    return DRIVER_UID  # fallback


def read_identity(handle, uid, debug=False):
    """Read identity parameters via standard RDM SET (0x20, PDL=0)."""
    results = {}

    def retarget(frame, dest):
        f = bytearray(frame)
        f[3:9] = dest
        ml = f[2]
        csum = sum(f[:ml]) & 0xFFFF
        f[ml] = (csum >> 8) & 0xFF
        f[ml + 1] = csum & 0xFF
        return bytes(f)

    for name, pid in IDENTITY_PIDS:
        frame = build_rdm(uid, TOOLBOX_UID, 0x20, pid)
        responses = rdm_send(handle, frame, polls=4, debug=debug)
        result = find_set_response(responses, pid)
        if result:
            results[name] = result['data']

    return results


def read_all_params(handle, debug=False):
    """Read all parameters: identity + 0xD0 extended registers."""
    # Discovery
    uid = discover_driver(handle, debug)

    # Identity
    identity = read_identity(handle, uid, debug)

    # Toolbox firmware
    fw_major = reg_read(handle, 0x00, debug)
    fw_minor = reg_read(handle, 0x01, debug)

    # 0xD0 extended registers
    params = {}
    for name, addr, desc, val_map in PARAM_MAP:
        val = d0_read(handle, addr, debug)
        if val is not None:
            params[name] = val  # (val_lo, val_hi)

    return {
        'uid': uid,
        'firmware': (fw_major, fw_minor),
        'identity': identity,
        'params': params,
    }


def write_param(handle, param_name, value, debug=False):
    """Write a parameter via 0xD0. Returns True if ACK received."""
    for name, addr, desc, val_map in PARAM_MAP:
        if name == param_name:
            if isinstance(value, int):
                val_lo = value & 0xFF
                val_hi = (value >> 8) & 0xFF
            elif isinstance(value, tuple) and len(value) == 2:
                val_lo, val_hi = value
            else:
                return False
            return d0_write(handle, addr, val_lo, val_hi, debug)
    return False


# ─── Display ─────────────────────────────────────────────────────────
def print_header(text):
    if console:
        console.print(f"\n[header]{'=' * 60}[/header]")
        console.print(f"[header]{text}[/header]")
        console.print(f"[header]{'=' * 60}[/header]")
    else:
        print(f"\n{'=' * 60}")
        print(f"{text}")
        print(f"{'=' * 60}")


def print_read_results(data):
    uid = data['uid']
    fw = data['firmware']
    identity = data['identity']
    params = data['params']

    print_header("eldoLED TOOLbox pro — Driver Read")

    if console:
        # Identity table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Parameter", style="label", no_wrap=True)
        table.add_column("Value", style="value")
        table.add_row("Driver UID", f"{uid[:2].hex()}:{uid[2:].hex()}")
        table.add_row("TOOLbox firmware", f"{fw[0]}.{fw[1]}" if fw else "unknown")

        if 'DEVICE_INFO' in identity and len(identity['DEVICE_INFO']) >= 19:
            d = identity['DEVICE_INFO']
            model = (d[2] << 8) | d[3]
            cat = (d[4] << 8) | d[5]
            sw = int.from_bytes(d[6:10], 'big')
            footprint = (d[10] << 8) | d[11]
            start = (d[14] << 8) | d[15]
            table.add_row("Protocol", f"{d[0]}.{d[1]}")
            table.add_row("Model", f"0x{model:04x}")
            table.add_row("Category", f"0x{cat:04x}")
            table.add_row("Software", f"0x{sw:010x}")
            table.add_row("DMX footprint", str(footprint))
            table.add_row("Start address", str(start))
            table.add_row("Sensors", str(d[18]))

        if 'MODEL' in identity:
            table.add_row("Model label", identity['MODEL'].rstrip(b'\x00').decode('ascii', 'replace'))
        if 'MANUFACTURER' in identity:
            table.add_row("Manufacturer", identity['MANUFACTURER'].rstrip(b'\x00').decode('ascii', 'replace'))
        if 'SENSOR_0' in identity and len(identity['SENSOR_0']) >= 5:
            s = identity['SENSOR_0']
            smin = int.from_bytes(s[4:6], 'big', signed=True)
            smax = int.from_bytes(s[6:8], 'big', signed=True)
            sname = s[13:].decode('ascii', 'replace') if len(s) > 13 else ''
            table.add_row("Sensor 0", f"type {s[1]} unit {s[2]} range {smin}..{smax} '{sname}'")

        console.print(table)

        # Extended parameters table
        print_header("Extended Parameters (0xD0 registers)")
        ptable = Table(show_header=True, box=None, padding=(0, 2))
        ptable.add_column("Parameter", style="param", no_wrap=True)
        ptable.add_column("Addr", style="addr", justify="right")
        ptable.add_column("Lo", justify="right")
        ptable.add_column("Hi", justify="right")
        ptable.add_column("Decoded", style="value")

        for name, addr, desc, val_map in PARAM_MAP:
            if name in params:
                vlo, vhi = params[name]
                decoded = f"0x{vlo:02x}"
                if val_map and vlo in val_map:
                    decoded = f"{val_map[vlo]} (0x{vlo:02x})"
                elif name.startswith("current_cs"):
                    raw = (vhi << 8) | vlo
                    decoded = f"{raw - 0x4000} mA (raw 0x{raw:04x})"
                elif name == "ntc_throttling_temp":
                    decoded = f"{vlo} °C"
                elif name == "power_scaling":
                    decoded = f"{vlo} / 255"
                ptable.add_row(name, f"0x{addr:04x}", f"0x{vlo:02x}", f"0x{vhi:02x}", decoded)

        console.print(ptable)
        console.print(f"\n[dim]Read complete. {len(params)} parameters read.[/dim]")

    else:
        # Plain text fallback
        print(f"  UID: {uid[:2].hex()}:{uid[2:].hex()}")
        print(f"  Firmware: {fw[0]}.{fw[1]}" if fw else "  Firmware: unknown")
        if 'DEVICE_INFO' in identity and len(identity['DEVICE_INFO']) >= 19:
            d = identity['DEVICE_INFO']
            print(f"  Start address: {(d[14] << 8) | d[15]}")
        if 'MODEL' in identity:
            print(f"  Model: {identity['MODEL'].rstrip(b'\\x00').decode('ascii', 'replace')}")
        if 'MANUFACTURER' in identity:
            print(f"  Manufacturer: {identity['MANUFACTURER'].rstrip(b'\\x00').decode('ascii', 'replace')}")
        print("\nExtended parameters:")
        for name, addr, desc, val_map in PARAM_MAP:
            if name in params:
                vlo, vhi = params[name]
                print(f"  0x{addr:04x} {name}: lo=0x{vlo:02x} hi=0x{vhi:02x}")


def print_write_result(name, addr, val_lo, val_hi, success):
    if console:
        status = "[ok]✓ written[/ok]" if success else "[error]✗ no ACK[/error]"
        console.print(f"  [param]{name}[/param] [addr]0x{addr:04x}[/addr] = 0x{val_lo:02x} 0x{val_hi:02x}  {status}")
        if success:
            console.print(f"  [dim]Value stored. May need driver power cycle to take effect.[/dim]")
    else:
        print(f"  {name} 0x{addr:04x} = 0x{val_lo:02x} 0x{val_hi:02x}  {'OK' if success else 'NO ACK'}")


# ─── Interactive menu ────────────────────────────────────────────────
def interactive_menu(handle, debug=False):
    """Interactive read/write menu with dark theme."""
    while True:
        print_header("eldoLED TOOLbox pro — Interactive")
        if console:
            console.print("[1] Read all parameters")
            console.print("[2] Write a parameter")
            console.print("[3] Dump to file")
            console.print("[4] Send DMX levels")
            console.print("[5] Quit")
            choice = Prompt.ask("\nChoice", default="1")
        else:
            print("1) Read all  2) Write  3) Dump  4) Send DMX  5) Quit")
            choice = input("Choice: ").strip()

        if choice == "1":
            data = read_all_params(handle, debug)
            print_read_results(data)

        elif choice == "2":
            if console:
                table = Table(show_header=True, box=None, padding=(0, 2))
                table.add_column("#", style="dim")
                table.add_column("Parameter", style="param")
                table.add_column("Addr", style="addr")
                table.add_column("Description")
                for i, (name, addr, desc, _) in enumerate(PARAM_MAP):
                    table.add_row(str(i), name, f"0x{addr:04x}", desc)
                console.print(table)

                idx = Prompt.ask("\nParameter #", default="0")
                try:
                    idx = int(idx)
                    name, addr, desc, val_map = PARAM_MAP[idx]
                except (ValueError, IndexError):
                    console.print("[error]Invalid selection[/error]")
                    continue

                if val_map:
                    for v, d in val_map.items():
                        console.print(f"  0x{v:02x} = {d}")
                console.print(f"\n[label]{name}[/label] at [addr]0x{addr:04x}[/addr]")
                console.print(f"[dim]{desc}[/dim]")
                val_str = Prompt.ask("New value (hex, e.g. 0x0c or decimal)", default="0")

                if val_str.startswith("0x") or val_str.startswith("0X"):
                    val = int(val_str, 16)
                else:
                    val = int(val_str)

                if not Confirm.ask(f"Write 0x{val:02x} to {name}?"):
                    continue
            else:
                for i, (name, addr, desc, _) in enumerate(PARAM_MAP):
                    print(f"  {i}: {name} (0x{addr:04x}) — {desc}")
                idx = int(input("Parameter #: "))
                name, addr, desc, val_map = PARAM_MAP[idx]
                val = int(input("New value (hex or dec): "), 0)
                if input(f"Write 0x{val:02x} to {name}? [y/N] ").lower() != 'y':
                    continue

            success = write_param(handle, name, val, debug)
            print_write_result(name, addr, val & 0xFF, (val >> 8) & 0xFF, success)

        elif choice == "3":
            data = read_all_params(handle, debug)
            fname = os.path.expanduser(
                f"~/eldotool-reads/driver_{data['uid'].hex()}_"
                f"{time.strftime('%Y%m%d_%H%M%S')}.txt"
            )
            os.makedirs(os.path.dirname(fname), exist_ok=True)
            with open(fname, "w") as f:
                f.write(f"eldoLED driver read — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"UID: {data['uid'][:2].hex()}:{data['uid'][2:].hex()}\n")
                fw = data['firmware']
                f.write(f"Firmware: {fw[0]}.{fw[1]}\n\n")
                f.write("Extended parameters (0xD0):\n")
                for name, _, _, _ in [(n, a, d, v) for n, a, d, v in PARAM_MAP if n in data['params']]:
                    vlo, vhi = data['params'][name]
                    f.write(f"  {name}: lo=0x{vlo:02x} hi=0x{vhi:02x}\n")
            if console:
                console.print(f"\n[ok]Saved to {fname}[/ok]")
            else:
                print(f"\nSaved to {fname}")

        elif choice == "4":
            if console:
                spec = Prompt.ask("Levels (CH=VAL, e.g. 1=128,2=64)", default="1=128,2=128,3=128,4=128")
                sec_s = Prompt.ask("Seconds to hold", default="4")
            else:
                spec = input("Levels (CH=VAL): ").strip()
                sec_s = input("Seconds to hold [4]: ").strip() or "4"
            try:
                levels = parse_dmx_levels(spec)
                seconds = float(sec_s)
            except ValueError as exc:
                if console:
                    console.print(f"[error]{exc}[/error]")
                else:
                    print(exc)
                continue
            if console:
                console.print(f"[warn]Streaming {levels} for {seconds:.1f}s. Fail mode takes over when it stops.[/warn]")
            else:
                print(f"Streaming {levels} for {seconds:.1f}s. Fail mode takes over when it stops.")
            sent, echo, _frame = send_dmx_levels(handle, levels, seconds=seconds, debug=debug)
            echo_b = echo[0] if echo else None
            if console:
                console.print(f"[ok]Sent {sent} frames. First echo byte: {echo_b:#04x}[/ok]" if echo_b is not None
                              else f"[error]Sent {sent} frames, no USB echo[/error]")
            else:
                print(f"Sent {sent} frames. First echo byte: {echo_b}")

        elif choice == "5":
            break


# ─── Main ───────────────────────────────────────────────────────────
def main():
    debug = '--debug' in sys.argv
    read_only = '--read' in sys.argv
    interactive = '--interactive' in sys.argv

    ctx = ctypes.c_void_p()
    rc = libusb.libusb_init(ctypes.byref(ctx))
    if rc != 0:
        print("libusb_init failed")
        return 1

    if console:
        console.print("[header]Opening TOOLbox pro (VID 04d8 PID ff00)...[/header]")
    else:
        print(f"Opening TOOLbox pro (VID {VID:04x} PID {PID:04x})...")

    handle = libusb.libusb_open_device_with_vid_pid(ctx, VID, PID)
    if not handle:
        if console:
            console.print("[error]TOOLbox not found. Is it plugged in?[/error]")
        else:
            print("TOOLbox not found.")
        libusb.libusb_exit(ctx)
        return 1

    rc = libusb.libusb_claim_interface(handle, 0)
    if rc != 0:
        if console:
            console.print("[error]Cannot claim USB interface. Close FluxTool/Wine first.[/error]")
        else:
            print("claim_interface failed — close FluxTool/Wine first.")
        libusb.libusb_close(handle)
        libusb.libusb_exit(ctx)
        return 1

    if console:
        console.print("[ok]TOOLbox connected.[/ok]\n")
    else:
        print("TOOLbox connected.\n")

    try:
        if interactive:
            interactive_menu(handle, debug)
        elif read_only or (len(sys.argv) == 1):
            data = read_all_params(handle, debug)
            print_read_results(data)
        elif '--write' in sys.argv:
            # --write PARAM VALUE
            idx = sys.argv.index('--write')
            if idx + 2 >= len(sys.argv):
                print("Usage: eldotool2.py --write PARAM VALUE")
                return 1
            param_name = sys.argv[idx + 1]
            val_str = sys.argv[idx + 2]
            val = int(val_str, 0)
            # Find param
            found = False
            for name, addr, desc, val_map in PARAM_MAP:
                if name == param_name:
                    found = True
                    success = write_param(handle, name, val, debug)
                    print_write_result(name, addr, val & 0xFF, (val >> 8) & 0xFF, success)
                    break
            if not found:
                if console:
                    console.print(f"[error]Unknown parameter: {param_name}[/error]")
                else:
                    print(f"Unknown parameter: {param_name}")
                return 1
        elif '--dmx' in sys.argv:
            idx = sys.argv.index('--dmx')
            if idx + 1 >= len(sys.argv):
                print("Usage: eldotool2.py --dmx 1=128,2=64 [--seconds 4]")
                return 1
            levels = parse_dmx_levels(sys.argv[idx + 1])
            seconds = 3.0
            if '--seconds' in sys.argv:
                seconds = float(sys.argv[sys.argv.index('--seconds') + 1])
            if console:
                console.print(f"[warn]Streaming DMX {levels} for {seconds:.1f}s.[/warn]")
                console.print("[dim]Levels hold only while this runs. Then the driver uses its fail mode.[/dim]")
            else:
                print(f"Streaming DMX {levels} for {seconds:.1f}s.")
            sent, echo, _frame = send_dmx_levels(handle, levels, seconds=seconds, debug=debug)
            echo_b = echo[0] if echo else None
            ok = echo_b == 0x93
            if console:
                status = "[ok]dongle accepted the frame[/ok]" if ok else "[error]unexpected USB echo[/error]"
                console.print(f"  {sent} frames, first echo {echo_b}  {status}")
            else:
                print(f"  {sent} frames, first echo {echo_b}")
            if not ok:
                return 1
        else:
            data = read_all_params(handle, debug)
            print_read_results(data)
    finally:
        libusb.libusb_release_interface(handle, 0)
        libusb.libusb_close(handle)
        libusb.libusb_exit(ctx)
        if console:
            console.print("\n[dim]Done.[/dim]")
        else:
            print("\nDone.")


if __name__ == "__main__":
    sys.exit(main())
