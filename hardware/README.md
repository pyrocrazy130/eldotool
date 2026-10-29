# Open TOOLbox

Goal: keep programming POWERdrive 50U-M4Z0X drivers if the eldoLED dongle dies or FluxTool stops running. Do not build a board from a guessed schematic.

## What the official dongle is

Part TLU20504-REV004. Datasheet name: eldoLED TOOLbox pro v18.11, HW Rev 4.2. CI code *26037Y. That firmware string matches the register read from the dongle on this laptop (18.11).

USB, measured on this laptop, not copied from a forum:

- VID 04d8, PID ff00, manufacturer string "eldoLED", product string "TOOLbox pro"
- Full speed, 12 Mbit/s. EP0 max packet 8 bytes. bcdDevice 14.70.
- One interface, vendor class 255/255/255. Bulk OUT 0x01, bulk IN 0x81, 64-byte packets.
- Self-powered, MaxPower 250 mA. No serial string.

bcdDevice 14.70 is not the 18.11 firmware. The 18.11 value comes from toolbox registers 0 and 1. Do not treat them as the same number.

The 8-byte EP0 and full-speed link are consistent with a Microchip full-speed USB part. The exact MCU is not known. Do not pick a PIC18F part number and design around it.

Official datasheet, filed here as docs/Datasheet-TOOLbox-pro.pdf:

- Mini-USB in, RJ45 out
- DMX: pin 1 DMX+, pin 2 DMX-, pin 7 shield
- DALI: pin 4 DALI-, pin 5 DALI+
- LEDcode: pin 6 LEDcode+, pin 8 LEDcode-
- Size about 76 x 32 x 25 mm, 30 g
- A galvanic USB isolator may be required. A laptop that is not grounded can damage the LED engine.

The programming cable in the box is TLC03051. It is not a CAT5 breakout. The DMX plug has three conductors soldered: orange/white, orange, brown/white. Two other 2-pin plugs (blue pair, and brown with green) do not come apart. Leave them as eldoLED soldered them. The house driver was read with the DMX plug on the driver DMX input.

Accessories, from the same datasheet, not needed for the house drivers:

- TLA20501, TOOLbox adapter, powerless programming
- PJ0035HH1 and PJ0050HH1, 3.5 mm and 5.0 mm Touch-and-Go handheld programmers

## Three protocols, one jack

FluxTool's ft_server talks to the dongle as three universes: DMX/RDM, DALI, and LEDcode (including a LEDcode 2 mode). Class names in that binary include UsbToolboxRawLedcodeInterface and UsbToolboxDaliInterface. That is why a clone that only speaks RDM is not a full TOOLbox. It may still be enough for this driver.

POWERdrive 50W design guide, 30 July 2020: configuration is done with the TOOLbox pro. The driver terminals marked LEDcode/NTC are the NTC thermistor input, not a second programming port. The house read used the DMX plug only, and RDM identity came back. So an open programmer for this driver starts as DMX/RDM on pins 1, 2, and 7.

Older FluxTool quick-start sheets say POWERdrive answers DMX/LedSync, and that LEDcode programming is for SOLOdrive and DUALdrive. Those sheets are old (they list POWERdrive 561/106, not the 50U). Do not assume the 50U ignores LEDcode. Do not assume it requires it either. The next experiment is to send the known-good RDM frames out of a plain RS-485 DMX port and see if the same UID comes back. Until that test, the open board is a plan, not a programmer.

Newer eldoLED families (ECOdrive Nano and similar) program over NFC, Zhaga Book 24/25, or a 3.3 V TTL USB bridge, part PUSB-TTL3v3-HH-1, using eldoLED studio. That is a different generation. It is not a drop-in for the 50U-M4Z0X.

## Practical backup, in order

1. Finish the Linux tool against the dongle we have. That already reads identity. Current, curve, and startup are the remaining software work. See docs/coverage.md.
2. Buy a spare TLU20504 if one is still sold. That is the only backup that is known to work today.
3. Open DMX/RDM interface, after a bench test: isolated RS-485, RJ45 pins 1, 2, and 7, 250 kbit/s, E1.11/E1.20. Send the discovery and identity frames from docs/protocol.md. If the driver answers, the dongle is not required for those fields.
4. Open LEDcode and DALI only if a capture shows this driver using those pins. Do not route those pairs "just in case" until the electrical levels are measured. DALI is not RS-485.

## Do not build yet

No schematic, no MCU choice, no pin claim beyond the datasheet RJ45 map. A wrong level on the LEDcode/NTC pair can look like a thermistor fault or worse. Measure before a board.
