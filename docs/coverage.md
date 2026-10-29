# Coverage

A full Linux replacement for FluxTool on a POWERdrive 50U-M4Z0X. Checked items are verified on the driver that was on the cable. Unchecked items are named in the POWERdrive 50W design guide or in ft_server strings. They are not decoded. Do not invent a PID or a register for them.

## Read, verified

- [x] TOOLbox present, firmware 18.11
- [x] RDM discovery, UID
- [x] DEVICE_INFO (PID 0x0060): model, category, software, footprint, personality, start address
- [x] DEVICE_MODEL_DESCRIPTION (0x0080)
- [x] MANUFACTURER_LABEL (0x0081)
- [x] DEVICE_LABEL (0x0082)
- [x] SENSOR_DEFINITION sensor 0 (0x0200)

## Named in FluxTool, not decoded

From the POWERdrive 50W design guide (30 July 2020), Config and Control sections:

- [ ] Drive current, per LED output, 1 mA steps
- [ ] Minimum dimming level
- [ ] Dimming curve (logarithmic, linear, soft-linear, square)
- [ ] NTC throttling temperature (default 70 C, ignored if no NTC is on the LEDcode/NTC terminals)
- [ ] Startup mode and fail mode, including the two static scenes
- [ ] Group scaling, active or inactive per output
- [ ] Interpolation: Off, Video, Colour, White, Glow. Default is Colour.

ft_server 2.66.10 also names these parameters. Names only. No register map yet.

- minimum_level
- dimming_curve
- ntc_throttling_temperature
- startup_behaviour
- startup_delay
- startup_fade_time
- extra_startup_delay
- startup_force_480ms_fade
- Daisy-chain mode
- Daisy-chain cluster mode, slave count

The Windows capture contains short frames that start with 0xD0 inside the same USB command as RDM. Those are not E1.20. They are the likely tunnel for the list above. Leave them unmapped until a capture shows the on-screen value next to the bytes, or until ft_server is disassembled far enough to name each address.

## Write

Not started. Read must match FluxTool on a field before that field is written. Change one field at a time. Startup and fail changes may not take effect until mains has been off for at least 3 seconds. Wrong current or an inactive output left active can damage the LED load. The design guide says FluxTool blocks some illegal current combinations at programming time. This tool does not, yet.
