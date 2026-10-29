#!/usr/bin/python3
"""Clickable window for the eldoLED TOOLbox tool.

Launch with the system Python (GTK4 + libadwaita). The Hermes venv does not
have those bindings.

    /usr/bin/python3 ~/Work/eldotool/eldotool_ui.py
"""
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eldotool2 as et

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk


def decode_param(name, vlo, vhi, val_map):
    if name.startswith("current_cs"):
        raw = (vhi << 8) | vlo
        return f"{raw - 0x4000} mA"
    if name == "ntc_throttling_temp":
        return f"{vlo} °C"
    if name == "power_scaling":
        return f"{vlo} / 255"
    if name == "network_resolution":
        # High byte is the resolution. The low byte is the start address.
        return {0x30: "8-bit", 0x20: "16-bit"}.get(vhi, f"0x{vhi:02x}")
    if name == "dmx_start_address":
        return str(vlo)
    if val_map and vlo in val_map:
        return val_map[vlo]
    if name.startswith("scene"):
        return f"{vlo}, {vhi}"
    return f"0x{vlo:02x}"


def interpret_write(name, text):
    text = text.strip()
    if not text:
        raise ValueError("Enter a value")
    val = int(text, 0)
    if name.startswith("current_cs") and not text.lower().startswith("0x") and val < 0x4000:
        if not 0 <= val <= 1400:
            raise ValueError("Current must be 0–1400 mA, or a raw 0x4xxx value")
        return 0x4000 + val, f"{val} mA (stored as 0x{0x4000 + val:04x})"
    if val < 0 or val > 0xFFFF:
        raise ValueError("Value must fit in two bytes")
    return val, f"0x{val & 0xFF:02x} / 0x{(val >> 8) & 0xFF:02x}"


class UsbWorker(threading.Thread):
    """Owns the dongle. The GTK thread only posts commands."""

    def __init__(self, emit):
        super().__init__(daemon=True, name="eldotool-usb")
        self.emit = emit
        self.q = queue.Queue()
        self.levels = [0, 0, 0, 0]
        self.hold = False
        self.seq = False
        self.fade = 1.0
        self.period = 2.0
        self.duty = 0.5
        self.seq_t0 = time.time()
        self._last_seq_ui = 0.0
        self.handle = None
        self.ctx = None
        self.alive = True

    def post(self, item):
        self.q.put(item)

    def run(self):
        self._open()
        while self.alive:
            timeout = 0.04 if ((self.hold or self.seq) and self.handle) else 0.25
            try:
                item = self.q.get(timeout=timeout)
            except queue.Empty:
                if self.handle and (self.hold or self.seq):
                    if self.seq:
                        self._apply_sequence()
                    self._send_levels()
                continue
            kind = item[0]
            try:
                if kind == "quit":
                    break
                elif kind == "open":
                    self._open()
                elif kind == "read":
                    self._read()
                elif kind == "write":
                    self._write(item[1], item[2])
                elif kind == "levels":
                    if not self.seq:
                        self.levels = [max(0, min(255, int(v))) for v in item[1][:4]]
                elif kind == "hold":
                    self.hold = bool(item[1]) and self.handle is not None
                    self.emit("hold", self.hold)
                elif kind == "seq":
                    self.seq = bool(item[1]) and self.handle is not None
                    if self.seq:
                        self.seq_t0 = time.time()
                    self.emit("seq", self.seq)
                elif kind == "seqparam":
                    self.fade = max(0.0, min(1.0, float(item[1])))
                    self.period = max(0.4, min(12.0, float(item[2])))
                    self.duty = max(0.05, min(1.0, float(item[3])))
            except Exception as exc:
                self.hold = False
                self.seq = False
                self.emit("error", str(exc))
                self.emit("hold", False)
                self.emit("seq", False)
        self._close()

    def _emit_status(self, text, ok=True):
        self.emit("status", (text, ok))

    def _open(self):
        self._close()
        ctx = et.ctypes.c_void_p()
        rc = et.libusb.libusb_init(et.ctypes.byref(ctx))
        if rc != 0:
            self._emit_status("libusb failed to start", ok=False)
            return
        handle = et.libusb.libusb_open_device_with_vid_pid(ctx, et.VID, et.PID)
        if not handle:
            et.libusb.libusb_exit(ctx)
            self._emit_status("TOOLbox not found. Plug it in and click Retry.", ok=False)
            return
        rc = et.libusb.libusb_claim_interface(handle, 0)
        if rc != 0:
            et.libusb.libusb_close(handle)
            et.libusb.libusb_exit(ctx)
            self._emit_status("Dongle is busy. Close FluxTool, then Retry.", ok=False)
            return
        self.ctx = ctx
        self.handle = handle
        self._emit_status("TOOLbox connected", ok=True)
        self._read()

    def _close(self):
        self.hold = False
        self.seq = False
        if self.handle:
            et.libusb.libusb_release_interface(self.handle, 0)
            et.libusb.libusb_close(self.handle)
            self.handle = None
        if self.ctx:
            et.libusb.libusb_exit(self.ctx)
            self.ctx = None

    def _read(self):
        if not self.handle:
            self._emit_status("Not connected", ok=False)
            return
        was_hold = self.hold
        was_seq = self.seq
        self.hold = False
        self.seq = False
        self._emit_status("Reading driver…", ok=True)
        data = et.read_all_params(self.handle)
        self.emit("read", data)
        uid = data["uid"]
        fw = data["firmware"]
        fw_s = f"{fw[0]}.{fw[1]}" if fw and fw[0] is not None else "?"
        self._emit_status(f"Connected  {uid[:2].hex()}:{uid[2:].hex()}  firmware {fw_s}", ok=True)
        if was_seq and self.handle:
            self.seq = True
            self.seq_t0 = time.time()
            self.emit("seq", True)
        elif was_hold and self.handle:
            self.hold = True
            self.emit("hold", True)

    def _write(self, name, value):
        if not self.handle:
            self._emit_status("Not connected", ok=False)
            return
        was_hold = self.hold
        was_seq = self.seq
        self.hold = False
        self.seq = False
        ok = et.write_param(self.handle, name, value)
        self.emit("write", (name, value, ok))
        if ok:
            self.hold = was_hold
            self.seq = was_seq
            self._read()
            return
        self._emit_status(f"No ACK writing {name}", ok=False)
        if was_seq and self.handle:
            self.seq = True
            self.emit("seq", True)
        elif was_hold and self.handle:
            self.hold = True
            self.emit("hold", True)

    def _send_levels(self):
        frame = bytearray(513)
        for i, val in enumerate(self.levels):
            frame[i + 1] = val
        try:
            echoes = et.send_protocol(self.handle, frame)
        except Exception as exc:
            self.hold = False
            self.seq = False
            self.emit("error", str(exc))
            self.emit("hold", False)
            self.emit("seq", False)
            return
        echo = echoes[0][0] if echoes and echoes[0] else None
        if echo != 0x93:
            self.hold = False
            self.seq = False
            self.emit("error", f"Dongle rejected the frame (echo {echo})")
            self.emit("hold", False)
            self.emit("seq", False)

    def _apply_sequence(self):
        """Triangle pulse on each output, staggered by a quarter cycle."""
        now = time.time()
        period = self.period if self.period > 0 else 2.0
        duty = self.duty
        peak = self.fade * 255.0
        elapsed = now - self.seq_t0
        levels = []
        for i in range(4):
            phase = (elapsed / period + i / 4.0) % 1.0
            if phase < duty:
                u = phase / duty
                tri = 1.0 - abs(2.0 * u - 1.0)
                levels.append(int(round(tri * peak)))
            else:
                levels.append(0)
        self.levels = levels
        if now - self._last_seq_ui >= 0.08:
            self._last_seq_ui = now
            self.emit("seqlevels", list(levels))


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="eldoLED TOOLbox")
        self.set_default_size(960, 760)
        self.params = {}
        self.selected = None
        self._syncing = False

        title = Adw.WindowTitle.new("eldoLED TOOLbox", "Looking for the dongle…")
        self.title = title
        header = Adw.HeaderBar()
        header.set_title_widget(title)
        self.retry_btn = Gtk.Button(label="Retry")
        self.retry_btn.connect("clicked", self._on_retry)
        header.pack_start(self.retry_btn)
        self.read_btn = Gtk.Button(label="Read")
        self.read_btn.connect("clicked", lambda *_: self.worker.post(("read",)))
        header.pack_end(self.read_btn)

        self.toast = Adw.ToastOverlay()

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        root.set_margin_top(12)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)

        root.append(self._build_dmx())
        root.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        root.append(self._build_params())

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(root)
        scroll.set_propagate_natural_height(True)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)
        self.toast.set_child(toolbar)
        self.set_content(self.toast)

        self.worker = UsbWorker(self._emit)
        self.worker.start()
        self.connect("close-request", self._on_close)

    def _build_dmx(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_hexpand(True)
        head = Gtk.Label(label="DMX output", xalign=0)
        head.add_css_class("title-2")
        box.append(head)
        note = Gtk.Label(
            label="Channels 1–4. Hold streams a fixed level. Sequence fades each output in turn. The toolbox LED blinks while frames are going out. Stop either one and fail mode takes the outputs back.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        box.append(note)

        self.scales = []
        self.value_labels = []
        for i in range(4):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name = Gtk.Label(label=f"Output {i + 1}", xalign=0, width_chars=10)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            scale.connect("value-changed", self._on_scale)
            val = Gtk.Label(label="0", width_chars=3, xalign=1)
            val.add_css_class("title-4")
            row.append(name)
            row.append(scale)
            row.append(val)
            box.append(row)
            self.scales.append(scale)
            self.value_labels.append(val)

        buttons = Gtk.Box(spacing=8)
        off = Gtk.Button(label="All off")
        off.connect("clicked", lambda *_: self._set_all(0))
        half = Gtk.Button(label="Half")
        half.connect("clicked", lambda *_: self._set_all(128))
        full = Gtk.Button(label="All full")
        full.connect("clicked", lambda *_: self._set_all(255))
        self.hold_btn = Gtk.ToggleButton(label="Hold output")
        self.hold_btn.add_css_class("suggested-action")
        self.hold_btn.set_hexpand(True)
        self.hold_btn.connect("toggled", self._on_hold)
        buttons.append(off)
        buttons.append(half)
        buttons.append(full)
        buttons.append(self.hold_btn)
        box.append(buttons)

        self.seq_btn = Gtk.ToggleButton(label="Sequence")
        self.seq_btn.set_hexpand(True)
        self.seq_btn.connect("toggled", self._on_seq)
        box.append(self.seq_btn)

        self.fade_scale, self.fade_label = self._param_slider(
            box, "Fade", 0, 100, 100, "%", self._on_seq_param
        )
        self.time_scale, self.time_label = self._param_slider(
            box, "Time", 0.4, 8.0, 2.0, "s", self._on_seq_param
        )
        self.duty_scale, self.duty_label = self._param_slider(
            box, "Duty", 10, 90, 50, "%", self._on_seq_param
        )
        seq_note = Gtk.Label(
            label="Fade is the peak. Time is one full cycle. Duty is how much of that cycle each output is fading; the rest it is off. The four outputs are a quarter-cycle apart.",
            xalign=0,
            wrap=True,
        )
        seq_note.add_css_class("dim-label")
        box.append(seq_note)
        return box

    def _param_slider(self, box, caption, low, high, default, unit, callback):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=caption, xalign=0, width_chars=10)
        step = 1 if high >= 10 else 0.1
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.set_value(default)
        scale.connect("value-changed", callback)
        shown = f"{default:.0f}{unit}" if high >= 10 else f"{default:.1f}{unit}"
        label = Gtk.Label(label=shown, width_chars=5, xalign=1)
        row.append(name)
        row.append(scale)
        row.append(label)
        box.append(row)
        return scale, label

    def _build_params(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(340, -1)
        head = Gtk.Label(label="Driver", xalign=0)
        head.add_css_class("title-2")
        box.append(head)
        self.identity_label = Gtk.Label(label="No read yet", xalign=0, wrap=True)
        self.identity_label.add_css_class("dim-label")
        box.append(self.identity_label)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.connect("row-selected", self._on_row)
        frame = Gtk.ScrolledWindow()
        frame.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame.set_min_content_height(280)
        frame.set_vexpand(True)
        frame.set_child(self.listbox)
        box.append(frame)

        write = Gtk.Box(spacing=8)
        self.value_entry = Gtk.Entry(placeholder_text="Value")
        self.value_entry.set_hexpand(True)
        self.write_btn = Gtk.Button(label="Write")
        self.write_btn.add_css_class("destructive-action")
        self.write_btn.set_sensitive(False)
        self.write_btn.connect("clicked", self._on_write_clicked)
        write.append(self.value_entry)
        write.append(self.write_btn)
        box.append(write)
        hint = Gtk.Label(
            label="Write changes a stored register, not the live DMX level. Current is entered in mA.",
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        box.append(hint)
        return box

    def _emit(self, kind, payload):
        GLib.idle_add(self._on_worker, kind, payload)

    def _on_worker(self, kind, payload):
        if kind == "status":
            text, ok = payload
            self.title.set_subtitle(text)
            if not ok:
                self.toast.add_toast(Adw.Toast.new(text))
        elif kind == "error":
            self.title.set_subtitle(payload)
            self.toast.add_toast(Adw.Toast.new(payload))
            if self.hold_btn.get_active():
                self._syncing = True
                self.hold_btn.set_active(False)
                self._syncing = False
            if self.seq_btn.get_active():
                self._syncing = True
                self.seq_btn.set_active(False)
                self._syncing = False
        elif kind == "hold":
            if self.hold_btn.get_active() != payload:
                self._syncing = True
                self.hold_btn.set_active(payload)
                self._syncing = False
            self.hold_btn.set_label("Holding — click to release" if payload else "Hold output")
        elif kind == "seq":
            if self.seq_btn.get_active() != payload:
                self._syncing = True
                self.seq_btn.set_active(payload)
                self._syncing = False
            self.seq_btn.set_label("Sequencing — click to stop" if payload else "Sequence")
        elif kind == "seqlevels":
            self._show_seq_levels(payload)
        elif kind == "read":
            self._show_read(payload)
        elif kind == "write":
            name, value, ok = payload
            msg = f"Wrote {name}" if ok else f"No ACK for {name}"
            self.toast.add_toast(Adw.Toast.new(msg))
        return False

    def _show_read(self, data):
        uid = data["uid"]
        identity = data.get("identity") or {}
        bits = [f"UID {uid[:2].hex()}:{uid[2:].hex()}"]
        if "DEVICE_INFO" in identity and len(identity["DEVICE_INFO"]) >= 16:
            d = identity["DEVICE_INFO"]
            bits.append(f"start {(d[14] << 8) | d[15]}")
            bits.append(f"footprint {(d[10] << 8) | d[11]}")
        if "MODEL" in identity:
            bits.append(identity["MODEL"].rstrip(b"\x00").decode("ascii", "replace"))
        self.identity_label.set_label(" · ".join(bits))

        self.params = data.get("params") or {}
        selected_name = self.selected
        self.listbox.remove_all()
        for name, addr, desc, val_map in et.PARAM_MAP:
            if name not in self.params:
                continue
            vlo, vhi = self.params[name]
            row = Gtk.ListBoxRow()
            row.param_name = name
            line = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            line.set_margin_top(6)
            line.set_margin_bottom(6)
            line.set_margin_start(10)
            line.set_margin_end(10)
            top = Gtk.Box()
            title = Gtk.Label(label=desc, xalign=0, hexpand=True)
            decoded = Gtk.Label(label=decode_param(name, vlo, vhi, val_map), xalign=1)
            decoded.add_css_class("accent")
            top.append(title)
            top.append(decoded)
            sub = Gtk.Label(label=f"{name}  0x{addr:04x}  lo 0x{vlo:02x}  hi 0x{vhi:02x}", xalign=0)
            sub.add_css_class("dim-label")
            line.append(top)
            line.append(sub)
            row.set_child(line)
            self.listbox.append(row)
            if name == selected_name:
                self.listbox.select_row(row)

    def _on_row(self, _box, row):
        if row is None:
            self.selected = None
            self.write_btn.set_sensitive(False)
            return
        self.selected = row.param_name
        self.write_btn.set_sensitive(True)
        vlo, vhi = self.params.get(self.selected, (0, 0))
        if self.selected.startswith("current_cs"):
            raw = (vhi << 8) | vlo
            self.value_entry.set_text(str(max(0, raw - 0x4000)))
        elif self.selected.startswith("scene"):
            self.value_entry.set_text(f"0x{vlo:02x}{vhi:02x}")
        else:
            self.value_entry.set_text(str(vlo))

    def _on_scale(self, *_args):
        if self._syncing:
            return
        vals = []
        for scale, label in zip(self.scales, self.value_labels):
            val = int(scale.get_value())
            vals.append(val)
            label.set_label(str(val))
        self.worker.post(("levels", vals))

    def _set_all(self, level):
        self._syncing = True
        try:
            for scale, label in zip(self.scales, self.value_labels):
                scale.set_value(level)
                label.set_label(str(level))
        finally:
            self._syncing = False
        self.worker.post(("levels", [level] * 4))

    def _on_hold(self, btn):
        if self._syncing:
            return
        if btn.get_active() and self.seq_btn.get_active():
            self._syncing = True
            self.seq_btn.set_active(False)
            self._syncing = False
            self.worker.post(("seq", False))
        self.worker.post(("hold", btn.get_active()))
        self.worker.post(("levels", [int(s.get_value()) for s in self.scales]))

    def _on_seq(self, btn):
        if self._syncing:
            return
        if btn.get_active() and self.hold_btn.get_active():
            self._syncing = True
            self.hold_btn.set_active(False)
            self._syncing = False
            self.worker.post(("hold", False))
        self._post_seq_params()
        self.worker.post(("seq", btn.get_active()))

    def _on_seq_param(self, *_args):
        fade = int(self.fade_scale.get_value())
        period = self.time_scale.get_value()
        duty = int(self.duty_scale.get_value())
        self.fade_label.set_label(f"{fade}%")
        self.time_label.set_label(f"{period:.1f}s")
        self.duty_label.set_label(f"{duty}%")
        self._post_seq_params()

    def _post_seq_params(self):
        self.worker.post((
            "seqparam",
            self.fade_scale.get_value() / 100.0,
            self.time_scale.get_value(),
            self.duty_scale.get_value() / 100.0,
        ))

    def _show_seq_levels(self, levels):
        self._syncing = True
        try:
            for scale, label, val in zip(self.scales, self.value_labels, levels):
                scale.set_value(val)
                label.set_label(str(val))
        finally:
            self._syncing = False

    def _on_write_clicked(self, *_args):
        name = self.selected
        if not name:
            return
        try:
            value, shown = interpret_write(name, self.value_entry.get_text())
        except ValueError as exc:
            self.toast.add_toast(Adw.Toast.new(str(exc)))
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Write {name.replace('_', ' ')}?",
            body=f"Store {shown}. This changes the driver register, not the live DMX level.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("write", "Write")
        dialog.set_response_appearance("write", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_write_confirm, name, value)
        dialog.present()

    def _on_write_confirm(self, _dialog, response, name, value):
        if response == "write":
            self.worker.post(("write", name, value))

    def _on_retry(self, *_args):
        self.worker.post(("open",))

    def _on_close(self, *_args):
        self.worker.post(("quit",))
        self.worker.join(timeout=3)
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.gifford.eldotool")

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(
            ".dim-label { opacity: 0.7; }\n.accent { font-weight: 600; }\n"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()


def main():
    app = App()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
