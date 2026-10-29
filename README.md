# eldotool

Linux programmer for eldoLED POWERdrive drivers through the TOOLbox pro USB dongle. No Wine, no FluxTool.

Tested on one POWERdrive with a TOOLbox pro (USB 04d8:ff00, firmware 18.11). It is not a full FluxTool replacement. DALI and LEDcode are not implemented.

## What it does

- Read driver identity and the extended registers FluxTool uses for current, scenes, fail mode, curve, interpolation, and start address.
- Write those registers. A write changes the stored value. Confirm it with a read-back.
- Send DMX out the dongle RJ45. Levels hold only while frames are streaming. When they stop, the driver uses its fail mode.

Writes and DMX change a live driver. Read first.

## Requirements

- Linux with libusb-1.0
- Python 3
- For the window: GTK 4 and libadwaita (`python3-gobject` on Debian, `gtk4` and `libadwaita` plus system Python on Arch)

The window must be launched with a Python that can import `gi`. A venv that does not have the system GTK bindings will not work.

## USB access

The dongle arrives with no udev rule, so only root can open it. Install `udev/70-eldoled-toolbox.rules` and reload udev:

```
sudo cp udev/70-eldoled-toolbox.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb
```

Unplug and replug the dongle after that. One driver, powered, on the programming cable.

## Run

```
python3 eldotool2.py              # read
python3 eldotool2.py --write dimming_curve 1
python3 eldotool2.py --dmx 1=0,2=0,3=0,4=0 --seconds 4
python3 eldotool2.py --interactive
python3 eldotool_ui.py            # clickable window
```

The window has Hold (fixed levels) and Sequence (a fade across the four outputs). Fade is the peak. Time is one cycle. Duty is how much of the cycle each output spends fading.

## Notes

`docs/` is the byte-level notes from reading this dongle and one driver. Some enum bytes are confirmed on that hardware. Others are still raw hex on purpose. Do not invent a label for a byte that is not in the map.

The official TOOLbox pro datasheet is eldoLED's. It is not in this repo.
