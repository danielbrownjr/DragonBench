# ESP32-S3 N16R8 target profile

> **Validation state: build-validated only. Physical flash/boot validation is
> pending.** No image has been flashed to or booted on this board yet.

Board facts below come from visual inspection of the physical board and its
silkscreen. Nothing here has been measured or exercised on the board.

- Module: ESP32-S3-WROOM-1, marked `MCN16R8`
- Flash: 16 MB
- PSRAM: 8 MB, Octal SPI
- Carrier: Lonely Binary pluggable-terminal development board, with BOOT and
  RESET buttons, two USB-C connectors, and an external USB-UART bridge
- Onboard RGB LED: GPIO48 (silkscreen `RGB@IO48`); see
  [Status RGB LED](#status-rgb-led)
- UART console: TX GPIO43, RX GPIO44
- Native USB: D- GPIO19, D+ GPIO20
- Convenience silkscreen labels: SPI SS GPIO10, MOSI GPIO11, SCK GPIO12,
  MISO GPIO13; I2C SDA GPIO8, SCL GPIO9. These are labels only, not evidence
  that the carrier wires anything to those pins.
- GPIO6 and GPIO7 are exposed on the pluggable terminals
- RF switch: none
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

Confirmed by visual inspection: an onboard RGB LED with its data on GPIO48
(silkscreen `RGB@IO48`). No power or enable GPIO is known, and none is
configured.

Not confirmed from a primary source (Lonely Binary's documentation could not
be fetched from this environment): the LED part. Secondary summaries of
Lonely Binary's guide describe it as a WS2812 on GPIO48 and mention a pad
marked `RGB` that must be bridged. DragonBench drives it as a WS2812, the same
as the N8R8. If the LED is not WS2812-compatible, or the pad is open, the
status light stays dark; it cannot affect other pins.

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
  wiring above. Build-validated only.
- Physical flash and boot: pending.
- Not validated: the status RGB LED, PSRAM detection and memory test at boot,
  reset and auto-download behavior through either USB-C connector, which USB-C
  connector reaches the USB-UART bridge and which reaches native USB, Wi-Fi,
  mDNS, workload execution, fan characterization, and electrical
  characterization.