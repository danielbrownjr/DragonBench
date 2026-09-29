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
- Onboard RGB LED: GPIO48 (silkscreen `RGB@IO48`)
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
Octal SPI PSRAM at 80 MHz, 80 MHz flash, and no RF-switch GPIO. It changes
only three things:

- `CONFIG_ESPTOOLPY_FLASHSIZE_16MB`
- `CONFIG_DB_TARGET_NAME="esp32s3-n16r8"`
- `CONFIG_DB_BOARD_RESERVED_GPIO=48`, so fixture wiring cannot claim the
  onboard RGB LED pin. DragonBench never drives GPIO48. Other board profiles
  do not reserve it.

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

On this board the fixture pin guards reject GPIO48 (onboard RGB LED) and the
Octal PSRAM pins GPIO33–37, along with the pins every board rejects: strapping
pins, native USB, the UART console, flash, nonexistent pins, and a gate that is
also the tach.

## Validation status

- ESP-IDF 5.3.5 builds: `baseline`, and `fan-characterization` with the
  wiring above. Build-validated only.
- Physical flash and boot: pending.
- Not validated: PSRAM detection and memory test at boot, reset and
  auto-download behavior through either USB-C connector, which USB-C connector
  reaches the USB-UART bridge and which reaches native USB, Wi-Fi, mDNS,
  workload execution, fan characterization, and electrical characterization.
