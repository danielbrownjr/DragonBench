# ESP32-S3 N16R8 target profile

> **Validation state: baseline image physically validated on one board
> (2026-09-29).** Flash, boot, PSRAM, the status LED, both USB-C paths, the
> access point, mDNS and the read-only API have been exercised. Fan
> characterization and the GPIO6/7 fixture wiring have not. See
> [Validation status](#validation-status).

Board facts below come from visual inspection of the physical board and its
silkscreen, and from Lonely Binary's interactive GPIO map for its ESP32-S3
Gold Edition board (screenshot supplied by Dan, 2026-09-29). Anything
exercised on the board is marked as such under
[Validation status](#validation-status).

- Module: ESP32-S3-WROOM-1, marked `MCN16R8`
- Flash: 16 MB
- PSRAM: 8 MB, Octal SPI
- Carrier: Lonely Binary pluggable-terminal development board, with BOOT and
  RESET buttons, two USB-C connectors, and an external USB-UART bridge
- USB-C connectors: labelled `UART` and `USB` on Lonely Binary's map (with
  the antenna at the top, `UART` is on the left and `USB` on the right).
  Observed on the board: the left connector enumerates as a USB-UART bridge
  (VID:PID `1A86:7522`, which Windows' WCH driver labels CH340K; the chip
  marking has not been inspected), and the right connector as the chip's
  native USB Serial/JTAG (`303A:1001`)
- Onboard RGB LED: GPIO48 (silkscreen `RGB@IO48`); see
  [Status RGB LED](#status-rgb-led)
- UART console: TX GPIO43, RX GPIO44
- Native USB: D- GPIO19, D+ GPIO20
- Convenience silkscreen labels: SPI SS GPIO10, MOSI GPIO11, SCK GPIO12,
  MISO GPIO13; I2C SDA GPIO8, SCL GPIO9. These are labels only, not evidence
  that the carrier wires anything to those pins.
- GPIO6 and GPIO7 are exposed on the pluggable terminals. Lonely Binary's
  map shows both as plain GPIO.
- Lonely Binary's map marks these as restricted: TX/RX (43/44), GPIO0, 19,
  20, and 48; strapping pins 3, 45 and 46; and GPIO35–37 as unusable (Octal
  PSRAM). GPIO33 and 34 are not broken out. DragonBench's fixture pin guards
  already reject all of these on this board.
- RF switch: none
- The GPIOs DragonBench uses or rejects match the N8R8, a different carrier
  (VCC-GND YD-ESP32-S3); see
  [pin compatibility](TARGET_ESP32S3.md#pin-compatibility-with-the-n16r8)
- Profile overlay: `sdkconfig.defaults.n16r8`, reported target `esp32s3-n16r8`

## Configuration

The overlay layers on the shared `sdkconfig.defaults`, which already selects
Octal SPI PSRAM at 80 MHz, 80 MHz flash, no RF-switch GPIO, and the status
RGB LED on GPIO48 (`CONFIG_DB_STATUS_RGB_GPIO=48`, no power GPIO). It changes
only two things:

- `CONFIG_ESPTOOLPY_FLASHSIZE_16MB`
- `CONFIG_DB_TARGET_NAME="esp32s3-n16r8"`

```text
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.n16r8" set-target esp32s3
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.n16r8" build
# or, with the same checks CI uses:
bash ci/build-esp32s3.sh n16r8
```

Delete a generated `sdkconfig` before switching profiles.

## Flash layout

The physical flash is 16 MB, and the image header declares 16 MB. The
DragonBench partition layout (`partitions.csv`) is shared with the 8 MB boards
and intentionally ends below 8 MB (at `0x720000`). The upper 8 MB is unused.
The layout already holds the current firmware, both OTA slots, and the scratch
workload partition, so it has not been redesigned for this board.

## Fan-characterization fixture pins

The intended DragonBench Rev 0 fan-characterization fixture wiring on this
board is GPIO6 to the gate of an external non-inverting N-channel MOSFET stage
(`CONFIG_DB_FAN_GATE_SINK_LEVEL=1`: GPIO high turns the stage on, which pulls
the fan PWM line low) and GPIO7 for the conditioned tach input. These are
provisional DragonBench bench fixture assignments. They are not JumpJet GPIO
assignments, product requirements, or fan safety thresholds. Hosted CI compiles
the `fan-characterization` profile for this board with this wiring. PPR stays
`0` (unknown).

On this board the fixture pin guards reject GPIO48 (status RGB LED) and the
Octal PSRAM pins GPIO33–37, along with the pins every board rejects: strapping
pins, native USB, the UART console, flash, nonexistent pins, and a gate that is
also the tach.

## Status RGB LED

Confirmed by visual inspection and by Lonely Binary's GPIO map: an onboard
RGB LED in a 5050-style package with its data on GPIO48 (silkscreen
`RGB@IO48`), which the map marks as a restricted pin. The map shows a
solder-pad pair labelled `RGB` directly beside the LED, and no power or enable
GPIO; none is configured.

Not confirmed from a primary source: the LED part (the map does not name it),
its supply rail, and whether the `RGB` pad has to be bridged. The pad on the
validated board was not inspected, but its LED works (see
[Validation status](#validation-status)).
Secondary summaries of Lonely Binary's guide describe the LED as a WS2812 on
GPIO48 and say the `RGB` pads must be bridged to use it. DragonBench drives it
as a WS2812, the same as the N8R8. If the LED is not WS2812-compatible, or the
pad is open, the status light stays dark; it cannot affect other pins.

DragonBench owns this LED as its status light, so experiment fixture wiring
may not use its pins: the fan-characterization build fails if the gate or
tach is set to one. The firmware drives it through the RMT peripheral (not
LEDC or PCNT), one frame per change, with no task or timer. It is off from
boot until the `ready` event, then solid dim green (green channel 16 of 255)
while the device is ready and idle. Starting a run turns it off before the
run's `phase_start` event, and it stays off until that run has ended. It
turns green again only after a run passes; after a failed or aborted run, or
a passed `CONTROLLED_REBOOT`, it stays off until a later run passes.

Off means dark, not unpowered: without a power GPIO the LED's idle current
remains part of the board's baseline load.

## Validation status

- ESP-IDF 5.3.5 builds: `baseline`, and `fan-characterization` with the
  wiring above. The `fan-characterization` image is build-validated only.

The `baseline` image from commit `153c6d1` (ESP-IDF 5.3.5, clean tree) was
flashed to and exercised on one board on 2026-09-29. No fixture, fan, GPIO6/7
wiring or 24 V supply was connected. Observed on that board:

- Identity: the boot event and `/api/v1/device` report target and
  `board_profile` `esp32s3-n16r8`, experiment profile `baseline`, and the
  build's git SHA, clean source tree and ESP-IDF version.
- Flash: esptool detects 16 MB (flash ID `46`/`4018`); the bootloader reports
  16 MB in DIO mode at 80 MHz and loads the partition table above.
- PSRAM: ESP-IDF's Octal PSRAM driver identifies an AP Memory generation-3,
  64 Mbit (8 MB) device, and the boot-time memory test passes. The full 8 MB
  is added to the heap at 80 MHz. Octal operation rests on that driver
  succeeding; ESP-IDF does not print a separate bus-mode line.
- Boot: complete boot logs over the `UART` connector show no warnings,
  panic, watchdog reset or brownout, and the device reaches `ready` about
  1.2 s after reset. RESET-button and bridge-RTS resets restart it to
  `ready`; both report reset reason `power_on`, which the ROM also uses for a
  cold power-on.
- `UART` connector: auto-download, flash writing with hash verification,
  RTS reset and the UART0 console log all work through it.
- `USB` connector: auto-download and flash writing with hash verification
  work. On a RESET press the port dropped out and re-enumerated, and boot
  finished before the host reopened it, so no boot log was captured there;
  use the `UART` connector for boot logs. Host-driven reset into the
  application over this connector was not established.
- Status LED: the factory firmware lit it, and under DragonBench it was dark
  after both a RESET press and a cold power-up, then green at `ready`
  (visual, untimed). The dark gap after a warm reset was clearly shorter,
  consistent with the LED holding its previous colour until `app_main` first
  drives it off. The observer described the green as bright, although the
  firmware sends 16 of 255.
- Network: the access point `DragonBench-<MAC suffix>` starts with WPA2 on
  channel 1. The web UI and the read-only API endpoints (`/api/v1/device`,
  `status`, `sensors`, `workloads`, `events`) answer, and the mDNS name
  resolves and serves the API from a client on the access point.

Still not validated: station mode (no credentials were present), host-driven
reset over the `USB` connector, the USB-UART bridge part (only its USB IDs
were seen), the LED part and supply and the state of its `RGB` pad, workload
execution, the `fan-characterization` image, the GPIO6/7 fixture wiring, fan
characterization, and electrical characterization.