# TinyS3[D] target profile

- Board: Unexpected Maker TinyS3[D], schematic revision D-P1
- SoC: ESP32-S3FN8 (8 MB embedded flash, no in-package PSRAM), silicon v0.2
- PSRAM: separate 8 MB Quad SPI chip; the board has no SIO4–SIO7 wiring, so
  Octal mode cannot work
- Flash: 8 MB, DIO, XMC vendor as reported by esptool
- USB: the chip's native USB Serial/JTAG peripheral (VID:PID `303A:1001`); there
  is no USB-UART bridge and no auto-reset circuit
- RF: a BGS12 switch selects the onboard antenna or the U.FL connector, driven
  by GPIO38 (low: onboard; high: U.FL)
- Profile overlay: `sdkconfig.defaults.tinys3d`, reported target
  `esp32s3-tinys3d`
- Validated framework: ESP-IDF 5.3.5, xtensa-esp-elf GCC 13.2.0

Build by layering the overlay on the shared defaults:

```text
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.tinys3d" set-target esp32s3
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.tinys3d" build
```

Building the N8R8 profile for this board aborts at every boot with
`octal_psram: PSRAM chip is not connected, or wrong PSRAM line mode`.

To flash, hold BOOT, tap RESET, and release BOOT so the ROM downloader
enumerates, then run from `build/`:

```text
python -m esptool --chip esp32s3 -p COMx --before no_reset write_flash "@flash_args"
```

esptool's post-flash RTS reset has no effect on this port. Unplug and replug
USB to boot the new image. The default `--before default_reset` failed with
`Write timeout` while CircuitPython was running. Boot logs appear on the
same native USB port only during startup, so attach a monitor before
power-cycling.

## RF switch

The firmware drives GPIO38 low before Wi-Fi starts
(`CONFIG_DB_RF_SWITCH_GPIO`). Before it did, every link on this board was
marginal: station association to a home network timed out
(`assoc -> init (0x400)`), phones
on the direct access point cycled through SA Query disassociation and WPA2
handshake failures, and repeatedly re-requested DHCP leases. A scan of the same
networks with each switch position, with nothing attached to the U.FL
connector, measured:

| GPIO38 | Networks seen | Strongest RSSI |
|---|---|---|
| high (U.FL, unterminated) | 4 | -86 dBm |
| low (onboard antenna) | 7 | -56 dBm |

With GPIO38 driven low, the board associated with the same home network and
obtained a DHCP lease on the first attempt. The pin level before the firmware
drove it was not measured, so why the 100 kΩ pull-down did not hold it low is
unconfirmed.

## Status RGB LED

From the TinyS3[D] schematic, Rev D-P1 (2025-06-04, `TinyS3D_P1.kicad_sch` in
Unexpected Maker's `esp32s3` repository, `series_d/schematics/`):

- LED: WS2812B (LED2, LED1010 package)
- Data: GPIO18 (`CONFIG_DB_STATUS_RGB_GPIO=18`)
- Power: the LED's VDD is GPIO17 itself, with no switch in between
  (`CONFIG_DB_STATUS_RGB_POWER_GPIO=17`). GPIO17 high powers it
  (`CONFIG_DB_STATUS_RGB_POWER_ACTIVE_LEVEL=1`), matching Unexpected Maker's
  TinyS3[D] helper, whose `set_pixel_power(True)` turns the pixel on.

GPIO38 remains the separate RF-switch resource above.

DragonBench owns this LED as its status light, so experiment fixture wiring
may not use its pins: the fan-characterization build fails if the gate or
tach is set to one. The firmware drives it through the RMT peripheral (not
LEDC or PCNT), one frame per change, with no task or timer. It is off from
boot until the `ready` event, then solid dim green (green channel 16 of 255)
while the device is ready and idle. Starting a run turns it off before the
run's `phase_start` event, and it stays off until that run has ended. It
turns green again only after a run passes; after a failed or aborted run, or
a passed `CONTROLLED_REBOOT`, it stays off until a later run passes.

Here off also means unpowered: after a dark frame, GPIO17 is driven low, so
the LED draws nothing during a run. GPIO17 stays low from boot until the
first green, and no data is clocked into the LED while it is unpowered.

## Validation status

Flash, automatic boot from SPI flash, the ESP-IDF PSRAM memory test (8 MB added
to the heap), the `ready` event, the direct access point, station association
and DHCP on a home network, station credentials saved through
`/api/v1/network/sta` persisting in NVS across reflashes, and mDNS on both
interfaces have been validated. The `/setup` page, workload execution, the
status RGB LED, and electrical characterization have not.
