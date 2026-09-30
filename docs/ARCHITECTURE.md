# Architecture

Each image is one SoC target, one of its board profiles, and one experiment
profile (see [experiment profiles](EXPERIMENT_PROFILES.md)). Within an image,
DragonBench has four deliberately narrow boundaries:

- `firmware/common`: workload names, run lifecycle, sequencing, and capability
  semantics. It knows nothing about GPIOs or ESP-IDF drivers. `db_experiment.h`
  is the single place that reads the experiment-profile choice. `db_fan.c`
  holds the fan-characterization stimulus lifecycle, gate-polarity mapping, and
  tach arithmetic behind a small pad-level seam, so release-on-every-path and
  both stage polarities are host-tested.
- `firmware/main`: direct ESP-IDF implementations for Wi-Fi, mDNS,
  HTTP, reset reason, SoC temperature, NVS, flash, inactive-OTA writes, reboot,
  and TCP traffic, shared by every SoC target. `fan_characterization.c`
  (static gate drive, LEDC stimulus, PCNT tach) compiles only into the
  fan-characterization experiment profile; see
  [fan characterization](FAN_CHARACTERIZATION.md). `build_provenance.cmake`
  records the source revision on every build.
- `firmware/targets/<soc>`: the SoC target layer, one `db_soc.h` per ESP-IDF
  target (`esp32s3`, `esp32c5`), selected by `IDF_TARGET`: the SoC name and
  measurement sources the image reports, the Wi-Fi bands it words, and whether
  a reviewed fixture pin map exists. SoC Kconfig defaults live in
  `sdkconfig.defaults.<soc>`, which ESP-IDF layers automatically. Each SoC
  target builds with its own ESP-IDF release (ESP32-S3 5.3.5, ESP32-C5 5.5.5;
  see [ESP32-C5 target](TARGET_ESP32C5.md)).
- `cli`, `web`, and `protocol`: clients and the stable public contract. They do
  not have privileged behavior paths. Multi-step orchestration, such as the
  fan duty sweep, lives on the host; firmware runs one primitive at a time.

There is intentionally no universal embedded HAL. A future target may implement
the protocol and workload semantics directly when a concrete need exists.

The v1 firmware has no dependency on dragon-core. Reusing it would currently add
product-oriented surface area without reducing the small target implementation.
This decision can be revisited for a specific neutral service, with its commit
pin and scope documented before adoption.

The firmware directly declares its ESP-IDF component dependencies and uses the
external `espressif/mdns` component pinned at 1.12.0. The checked-in
Component Manager lockfile `dependencies.lock` records the resolved ESP-IDF
5.3.5/ESP32-S3 graph; other SoC targets use `dependencies.lock.<soc>`;
generated configuration and downloaded component sources are not repository
inputs.
