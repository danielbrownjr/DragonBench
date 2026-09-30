# Architecture

Each image is one board profile plus one experiment profile (see
[experiment profiles](EXPERIMENT_PROFILES.md)). Within an image, DragonBench
has three deliberately narrow boundaries:

- `firmware/common`: workload names, run lifecycle, sequencing, and capability
  semantics. It knows nothing about GPIOs or ESP-IDF drivers. `db_experiment.h`
  is the single place that reads the experiment-profile choice. `db_fan.c`
  holds the fan-characterization stimulus lifecycle, gate-polarity mapping, and
  tach arithmetic behind a small pad-level seam, so release-on-every-path and
  both stage polarities are host-tested.
- `firmware/main`: direct ESP-IDF implementations for Wi-Fi, mDNS,
  HTTP, reset reason, SoC temperature, NVS, flash, inactive-OTA writes, reboot,
  and TCP traffic. `fan_characterization.c`
  (static gate drive, LEDC stimulus, PCNT tach) compiles only into the
  fan-characterization experiment profile; see
  [fan characterization](FAN_CHARACTERIZATION.md). `build_provenance.cmake`
  records the source revision on every build.
- `cli`, `web`, and `protocol`: clients and the stable public contract. They do
  not have privileged behavior paths. Multi-step orchestration, such as the
  fan duty sweep, lives on the host; firmware runs one primitive at a time.

There is intentionally no universal embedded HAL. A future target may implement
the protocol and workload semantics directly when a concrete need exists.

The v1 firmware has no dependency on dragon-core. Reusing it would currently add
product-oriented surface area without reducing the small target implementation.
This decision can be revisited for a specific neutral service, with its commit
pin and scope documented before adoption.

The ESP32-S3 target directly declares its ESP-IDF component dependencies and
uses the external `espressif/mdns` component pinned at 1.12.0. The checked-in
Component Manager lockfile records the resolved ESP-IDF 5.3.5/ESP32-S3 graph;
generated configuration and downloaded component sources are not repository
inputs.
