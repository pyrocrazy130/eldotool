# Bench diff, 2026-10-18

Driver on the programming cable. Not a house assignment. Originals are the FluxTool Read pasted the same day. Change only the fields below. Leave everything else, including startup mode, max aggregate, and channel count.

After the edits, hit Read again. The new numbers have to still be on the screen. If they snap back, the edit did not stick.

Then move the TOOLbox USB plug to this laptop. Leave the driver powered and the cable on it. Do not kill mains while scene 2 or fail mode is changed. Startup is Goto Scene 2, and fail mode is what the outputs do with no DMX.

## Changes

Scene 2 output 1: 128 to 129
Scene 2 output 2: 128 to 130
Scene 2 output 3: leave 128
Scene 2 output 4: leave 128
Current group 1: 310 to 311
Current group 2: 310 to 312
Current group 3: leave 310
Current group 4: leave 310
NTC throttling temperature: 70 to 73
Network start address: 1 to 7
Dimming curve: linear to logarithmic
Interpolation: White to Glow
Group 4 scaling: on to off
Group 1-3 scaling: leave on
Power scaling: 255 to 200
Network resolution: 8 bit to 16 bit
Fail mode: Goto Scene 1 to the other choice, if there is one
Group 4 channel mapping: 4 to 1

## Restore after the diff

Scene 2 outputs: 128, 128, 128, 128
Current groups: 310, 310, 310, 310
NTC: 70
Start address: 1
Curve: linear
Interpolation: White
Group 4 scaling: on
Power scaling: 255
Network resolution: 8 bit
Fail mode: Goto Scene 1
Group 4 channel mapping: 4
