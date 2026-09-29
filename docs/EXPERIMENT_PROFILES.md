# Experiment profiles

DragonBench is a characterization platform that grows one experiment at a time.
Every image is exactly:

- one **board profile**, the module or board it runs on
  (`CONFIG_DB_TARGET_NAME`: `esp32s3-n8r8`, `esp32s3-n16r8`, `esp32s3-tinys3d`), plus
- one **experiment profile**, the narrow characterization setup it carries
  (the `DB_EXPERIMENT_PROFILE` Kconfig choice).

An experiment profile is not a feature flag. Profiles are mutually exclusive,
each is reviewed as a whole, and each brings only the stimulus or acquisition
code, fixture settings, and workloads it needs. Two experiments are never
combined in one image. If a setup needs both, it is a new, separately reviewed
profile.

| Profile | Overlay | Adds | Status |
|---|---|---|---|
| `baseline` | none (explicit in `sdkconfig.defaults`) | ESP32-S3 module workloads only; no fixture I/O | Default |
| `fan-characterization` | `sdkconfig.defaults.fan-characterization` + untracked `sdkconfig.fan-characterization.local` | `FAN_PWM_HOLD`: bench PWM stimulus through an external open-drain stage, PCNT tach capture. Not product fan control. See [fan characterization](FAN_CHARACTERIZATION.md). | Build-verified, not hardware-validated |

Profiles such as thermistor or heater characterization may follow; none exists
yet.

## Building

Layer the board overlay, then at most one experiment overlay, then that
experiment's local wiring overlay if it has one:

```text
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.<board>;sdkconfig.defaults.<experiment>;sdkconfig.<experiment>.local" build
bash ci/build-esp32s3.sh <board> [experiment] [--expect-refusal]
```

Delete a generated `sdkconfig` before switching profiles.

## What every profile reports

`/api/v1/device` names the image so artifacts never need reverse-engineering:

- `board_profile` and `experiment_profile`
- `build`: `firmware_version`, `git_sha`, `source_tree` (`clean`, `dirty`, or
  `unknown`), and `esp_idf`. The revision is recorded on every build by
  `build_provenance.cmake`. It is `null`/`unknown` whenever git could not
  establish it; nothing is guessed.
- `device_id`
- `measurement_provenance`: each quantity of interest mapped to
  `dut.<peripheral>` (measured by this firmware), `derived.<rule>` (computed
  from DUT data), or `external` (bench instruments; DragonBench reports no
  value)

The boot event carries board profile, experiment profile, and revision, so a
serial log alone identifies the image. `heater_capability` and
`fan_control_capability` are `false` in every profile.

## Rules for a new profile

1. Add one entry to the `DB_EXPERIMENT_PROFILE` choice, with fixture options in
   an `if DB_EXPERIMENT_<NAME>` block. Wiring has no defaults and an
   unconfigured build fails with an `#error` per missing setting.
2. Add its name to `firmware/common/include/db_experiment.h`. That is the only
   file that reads `CONFIG_DB_EXPERIMENT_*`; code uses `DB_EXPERIMENT_<NAME>`.
3. Add `sdkconfig.defaults.<name>` that selects the profile and nothing else.
4. Compile its code only under `DB_EXPERIMENT_<NAME>`, and put testable logic in
   `firmware/common` behind a hardware seam, with native tests.
5. Add it to `ci/build-esp32s3.sh` (`all_experiments`, the symbols that must be
   absent elsewhere, and its wiring settings) and to CI.
6. Extend `measurement_provenance` with exactly what it measures, derives, or
   relies on externally.
7. Document it, and keep it free of product policy: no product thresholds,
   timeouts, or production pin assignments.

`tests/test_experiment_profiles.py` enforces rules 1–3 and 5.
