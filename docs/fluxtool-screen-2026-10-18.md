# FluxTool screen, 2026-10-18

Windows FluxTool Read of the driver on the programming cable. No fields were changed. Not a room assignment.

Fail mode: Goto Scene 1
Scene 1 outputs: 255, 255, 255, 255
Scene 2 outputs: 128, 128, 128, 128
Startup mode: Goto Scene 2
Dimming curve: linear
Group scaling 1-4: on
Interpolation: White
NTC throttling temperature: 70 C
Power scaling: 255
Max aggregate current: 3400 mA
Current output groups 1-4: 310 mA
Network resolution: 8 bit
Network start address: 1
Group channel mapping: 1, 2, 3, 4
Network channel count: 4

Compared to the 0xD0 table in d0-frame.md. Scene bytes and the 310 mA encoding match. Curve, interpolation, scaling, and the mode enums do not.
