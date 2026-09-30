# ESP32-S3 target profile

- Target: ESP32-S3, N8R8 module class (8 MB Quad SPI flash, 8 MB Octal SPI
  PSRAM)
- Observed silicon revision: v0.2
- Embedded flash: 8 MB, DIO mode, boya-vendor chip as reported by the ROM
  bootloader
- Embedded PSRAM: 8 MB, Octal SPI, AP vendor, generation 3 die, running at
  80 MHz
- Observed USB path: external WCH CH343P USB-UART bridge (enumerated as a
  generic "USB Serial Device"), not the chip's native USB Serial/JTAG
  peripheral used by the previous Super Mini board. Chip identity confirmed
  by physical inspection of the package marking ("WCH CH343P"); the earlier
  CH9102 identification was incorrect and could not be distinguished from
  CH343 by USB descriptor alone.
- Validated framework for this characterization run: ESP-IDF 5.3.1 (build,
  flash, and boot exercised on this module using this version)
- Validated compiler: xtensa-esp-elf GCC 13.2.0
- Current target-component constraint: ESP-IDF >=5.3.5; this is the project's
  declared floor and is unchanged by this migration. A successful build on
  5.3.1 for this specific characterization run does not by itself establish
  5.3.1 as the project-supported minimum.
- Minimum historically compatible ESP-IDF version: not established
- External component: espressif/mdns 1.12.0, exact pin
- Hostname: `dragonbench`
- Actuators: absent
- On-device electrical measurement: absent
- Available DUT signals: uptime, reset reason, network state, Wi-Fi RSSI when
  associated, workload/run state, and on-die temperature when the ESP-IDF
  temperature-sensor driver initializes successfully
- External evidence: voltage and current measurements from bench instruments

Wi-Fi credentials are local configuration. The target does not claim supply
voltage/current sensing. Brownout evidence is limited to the reset reason
reported after boot; it is not a calibrated voltage measurement.

DragonBench creates a Wi-Fi access-point netif and a station netif, and no
Ethernet netif. The access point always runs; the station joins a network only
when one is configured through Kconfig or the `/setup` page. Accordingly,
`sdkconfig.defaults` enables both predefined mDNS interfaces within its
two-entry capacity. A lost station connection is retried three times
immediately, then with backoff doubling from 5 s to a 60 s ceiling,
indefinitely; each attempt scans channels and can briefly interrupt
access-point clients. This profile is the default; the
[N16R8](TARGET_N16R8.md) and the [TinyS3[D]](TARGET_TINYS3D.md) have their own
profiles. Generated `sdkconfig` and `managed_components/` remain local; the
Component Manager lockfile is tracked to preserve the dependency graph used by
the validated build.

Octal SPI PSRAM shares the SPI0/SPI1 clock domain with flash on ESP32-S3, so
`sdkconfig.defaults` pins flash frequency to 80 MHz alongside
`CONFIG_SPIRAM_SPEED_80M`; a mismatched flash frequency is a documented cause
of boot failure on Octal-PSRAM modules. This configuration has now been
exercised on physical hardware: the device booted automatically into
`SPI_FAST_FLASH_BOOT`, detected the 8 MB Octal PSRAM device, and passed the
ESP-IDF SPI SRAM memory test without manual BOOT-button intervention.

USB flashing (via the external CH343P bridge) and normal application boot
have been validated on this module. The image flashed with
verified hashes, hard-reset automatically, detected and successfully tested
the 8 MB PSRAM, and reached the DragonBench `ready` event with no panic,
watchdog, or brownout reset observed. On-device Wi-Fi/mDNS connectivity, API
calls over Wi-Fi, workloads, and electrical characterization remain
unvalidated on this module.

## Status RGB LED

The N8R8 board is the original DragonBench board, a VCC-GND YD-ESP32-S3
(confirmed by Dan, 2026-09-29; it is not a Lonely Binary board). Its published
schematic (YD-ESP32-S3-COREBOARD V1.4, 2022-09-23) includes the CH343P bridge
observed on this module. From that schematic:

- LED: XL-5050RGBC-WS2812B, powered from the 5 V rail (not a GPIO)
- Data: GPIO48, through a 0 Ω 0603 link labelled `RGB`
- No power or enable GPIO

Not yet checked on the physical board: whether the `RGB` link is fitted. If
it is open, the LED is disconnected and the status light simply stays dark.

DragonBench owns this LED as its status light, so experiment fixture wiring
may not use its pins: the fan-characterization build fails if the gate or
tach is set to one. The firmware drives it through the RMT peripheral (not
LEDC or PCNT), one frame per change, with no task or timer. It is off from
boot until the `ready` event, then solid dim green (green channel 16 of 255)
while the device is ready and idle. Starting a run turns it off before the
run's `phase_start` event, and it stays off until that run has ended. It
turns green again only after a run passes; after a failed or aborted run, or
a passed `CONTROLLED_REBOOT`, it stays off until a later run passes.

Off means dark. The LED stays powered from 5 V, so its idle current remains
part of the board's baseline load during measurement. Nothing about the LED
has been observed on hardware through this change.

## Pin compatibility with the N16R8

The N8R8 (VCC-GND YD-ESP32-S3) and the [N16R8](TARGET_N16R8.md) (Lonely
Binary Gold Edition) are different carriers, but DragonBench deliberately
treats the pins it cares about identically on both. VCC-GND's pin table and
schematic V1.4, and Lonely Binary's GPIO map, agree on these:

| GPIO | Both boards | DragonBench |
|---|---|---|
| 6, 7 | plain GPIO on the headers, nothing onboard | fan fixture gate and tach |
| 48 | onboard RGB LED data | status light; fixture wiring rejected |
| 35–37 | used by the Octal PSRAM, unavailable (33, 34 not broken out) | rejected |
| 19, 20 | native USB D-/D+ on its own USB-C connector | rejected |
| 43, 44 | UART0 TX/RX to the USB-UART bridge | rejected |
| 0, 3, 45, 46 | strapping | rejected |

That is the only equivalence claimed. The carriers still differ, and each
target profile records its own:

- flash: 8 MB here, 16 MB on the N16R8
- USB-UART bridge: CH343P here; not identified on the N16R8
- RGB LED: a 5 V WS2812B behind a 0 Ω `RGB` link here; on the N16R8 the part
  and supply are unconfirmed, beside a solder pad labelled `RGB`
- YD-only parts on pins DragonBench already rejects: TX and RX LEDs on
  GPIO43/44, a 10 kΩ pull-up to 3.3 V on GPIO3 through a `USB-JTAG` 0 Ω
  link, the BOOT button and DTR/RTS auto-program transistors on GPIO0 and EN
- connector labels: `UART` and `USB` are Lonely Binary's; the YD's two USB-C
  ports go to the CH343P and to native USB (GPIO19/20)

## Partition layout

The 8 MB layout uses two 3 MB OTA app slots so the inactive-partition workload
has a real target, plus a 1 MB scratch partition. There is no factory app
partition. The exact layout is maintained in `partitions.csv`.
