# Fan-characterization experiment profile

> **BENCH CHARACTERIZATION EQUIPMENT — NOT PRODUCT FAN CONTROL.** This
> experiment profile drives only the gate of an external open-drain stage and
> counts tach edges.
> It has no closed loop, no thresholds, no heater, and no fan-safety policy.
> `heater_capability` and `fan_control_capability` remain `false`.

`fan-characterization` is one of DragonBench's
[experiment profiles](EXPERIMENT_PROFILES.md): an image built with it reports
`"experiment_profile": "fan-characterization"`.

Status: firmware, API, and host tooling are implemented and build-verified; no
part of the fixture has run on hardware. The wiring is still to be defined, see
[Open items](#open-items).

The first specimen is the JumpJet Sanyo Denki `9GA0424P3J001` candidate. Its
plan and evidence record are JumpJet's
`docs/hardware/9ga0424p3j001-characterization.md`. DragonBench supplies a
stimulus and raw tach counts for that plan. It defines no JumpJet value: no
minimum duty, RPM proof threshold, fan-proof timeout, stall threshold, PWM
frequency, PPR, or production GPIO.

## What it adds

| Piece | Where |
|---|---|
| `DB_EXPERIMENT_FAN_CHARACTERIZATION` choice entry and wiring options | `Kconfig.projbuild`, `sdkconfig.defaults.fan-characterization` |
| `FAN_PWM_HOLD` workload | `firmware/common/db_run.c` (registry, validation) |
| Stimulus lifecycle and tach arithmetic, host-tested | `firmware/common/db_fan.c` |
| Static gate drive, LEDC stimulus, and PCNT tach capture | `firmware/targets/esp32s3/main/fan_characterization.c` |
| `fan-sweep` host command | `cli/dragonbench/main.py` |

Every other profile, including `baseline`, reports `FAN_PWM_HOLD` as
`unsupported` (reason `requires fan-characterization experiment profile`),
rejects it with HTTP 400, and links no LEDC, PCNT, or fan-characterization
code. CI checks that absence in the ELF.

## Electrical model

```text
 DragonBench GPIO ── gate/base ─┐        fan PWM lead (brown, per the San Ace
 (CONFIG_DB_FAN_PWM_GATE_GPIO)  │        convention; verify on the specimen)
                               ┌┴┐             │
 gate resistor to release level│ │ external    │
                               └┬┘ open-drain ─┘ drain/collector
                                │   stage        source/emitter ── fan GND
                                                                   = bench GND
 fan tach lead (yellow, verify) ── external pull-up to 3.3 V ── conditioning ──
                                   DragonBench GPIO (CONFIG_DB_FAN_TACH_GPIO)
```

- **The firmware drives only the transistor gate.** No DragonBench pin connects
  to a fan lead.
- **`sink_duty_pct`** is the fraction of time the external stage conducts and
  pulls the fan PWM line low. It is an electrical quantity. How the fan responds
  to it, including at 0 % and 100 %, is what the bench is there to measure.
- **The endpoints are static, not PWM.** 0 % holds the gate at its release
  level (`stimulus: static_release`) and 100 % holds it at its sink level
  (`stimulus: static_sink`), as plain GPIO outputs. Only values strictly
  between use LEDC (`stimulus: pwm`), so the LEDC compare value is always
  1..2^bits−1. On ESP32-S3, a duty of 2^duty_resolution can overflow the LEDC
  duty counter (ESP-IDF 5.3.5 LEDC documentation), so it is never programmed.
- **Released** means the gate is at its release level, so the stage is off and
  the fan PWM line is left to the fan's own input circuit. The firmware makes no
  claim about fan speed when the line is released.
- `CONFIG_DB_FAN_GATE_SINK_LEVEL` states the gate level that makes the stage
  sink: `1` for a non-inverting stage (N-channel MOSFET or NPN), `0` for an
  inverting one. The opposite level is the release level. An inverting stage
  inverts the pad, not the duty.

### Released on every path

| Moment | Mechanism |
|---|---|
| Power-up, reset, flashing, panic, brownout | The GPIO is an input with no firmware drive. The external gate resistor must hold the stage off. The firmware never enables an internal pull on the gate. |
| Boot | `fan_characterization_boot()` is the first statement of `app_main`. It drives the release level and reads the pad back. |
| Run start | `db_fan_hold` releases and verifies the line, then confirms tach capture is ready, before any actuation. If either fails, nothing is actuated. |
| Run end, abort, and every error | `db_fan_hold` has one exit path, which releases and verifies the line. |
| `esp_restart` (including `CONTROLLED_REBOOT`) | Shutdown handler releases the line. |

Every static drive (release or 100 % sink) writes the target level to the
output register first, then moves the pad from LEDC to a plain GPIO output, so
the switch cannot glitch to the other level. Which gate level sinks is decided
in the platform-neutral layer from `CONFIG_DB_FAN_GATE_SINK_LEVEL`, where native
tests cover both polarities at 0 %, PWM, and 100 %. Verification reads back the **pad** level. It does not
observe the transistor or the fan line; confirm those on the scope.

A release that cannot be verified is reported as `"released": false` with
`fixture_error`, a `fault` event, and a `fail` result. `/api/v1/status` shows
`bench_stimulus.fan_fixture.line_state` as `release_failed`.

## Configuration

Every fixture setting defaults to unset. An overlay without wiring stops the
build with one `#error` per missing setting. A reserved or conflicting pin also
fails the build: strapping pins (0, 3, 45, 46), USB (19, 20), flash/PSRAM
(26–32), Octal PSRAM data pins on octal profiles (33–37), the UART0 console
(43, 44), `CONFIG_DB_RF_SWITCH_GPIO`, or the gate and tach sharing one pin.
Those rules only exclude pins known to be taken; they do not choose one.

Create an untracked `sdkconfig.fan-characterization.local` (ignored by Git)
stating the wired fixture:

```text
CONFIG_DB_FAN_PWM_GATE_GPIO=<gate GPIO>
CONFIG_DB_FAN_GATE_SINK_LEVEL=<0|1>
CONFIG_DB_FAN_TACH_GPIO=<tach GPIO>
# Optional:
# CONFIG_DB_FAN_TACH_INTERNAL_PULLUP=y      # default off: use an external pull-up
# CONFIG_DB_FAN_TACH_GLITCH_FILTER_NS=<0..12700>
# CONFIG_DB_FAN_TACH_PPR=<1..16>            # only once PPR is established
# CONFIG_DB_FAN_TACH_PPR_EVIDENCE="<record that established it>"
```

`CONFIG_DB_FAN_TACH_PPR` stays `0` (unknown) until independent evidence, such
as an optical tachometer compared against tach edges, establishes it. A non-zero
PPR without `CONFIG_DB_FAN_TACH_PPR_EVIDENCE` fails the build. With PPR unknown,
events carry `"ppr": null, "rpm": null` and RPM is never derived.

Build: board overlay, then experiment overlay, then local wiring:

```text
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.tinys3d;sdkconfig.defaults.fan-characterization;sdkconfig.fan-characterization.local" build
# or, with the same checks CI uses:
bash ci/build-esp32s3.sh tinys3d fan-characterization
```

Delete a generated `sdkconfig` before switching profiles. At boot the serial log
prints a `FAN-CHARACTERIZATION EXPERIMENT PROFILE` warning with the configured
pins and line state.

## FAN_PWM_HOLD

```text
POST /api/v1/runs
{"workload": "FAN_PWM_HOLD", "pwm_hz": <int>, "sink_duty_pct": <number>, "duration_ms": <int>}
```

| Parameter | Accepted | Notes |
|---|---|---|
| `pwm_hz` | integer 10–50000 | Limits of the fixture generator, not a fan specification. They keep at least 10-bit duty resolution from the 80 MHz LEDC clock. Required even at 0 % and 100 %, where no PWM is generated, so a sweep is uniform. |
| `sink_duty_pct` | 0–100 in 0.1 steps | 0 and 100 are exact static levels; values between are quantized to the LEDC resolution and the produced value is reported. |
| `duration_ms` | integer 1–3600000, required | No implied default for a stimulus. |

All three are required and validated on the device. `pwm_hz` or
`sink_duty_pct` on any other workload is rejected. A hold runs as follows:

1. Plan the stimulus (static release, PWM, or static sink).
2. Release the line and verify it.
3. Confirm tach capture is ready. Tach edges are the evidence this workload
   exists for, so an unavailable tach refuses the run (`tach_unavailable`)
   before anything is actuated.
4. Actuate the planned stimulus.
5. Clear the tach counter and open the window immediately after.
6. Hold, checking for abort every 20 ms.
7. Read the count and close the window.
8. Release, on this and every earlier exit.

Only one run is active at a time.

Tach capture uses PCNT on the tach GPIO. It counts falling edges only, so
counted edges equal tach pulses. An accumulating watch point extends the 16-bit
hardware counter.

### Events

The normal run lifecycle applies: `phase_start` → (`fault`) → `phase_end` →
`run_complete`, all with `run_id`, `seq`, and `uptime_ms` for correlation with
external captures and DragonSniff. `phase_start` is emitted before the stimulus
is applied, and `phase_end` after the line is released.

`parameters` (both phase events):

```json
{"pwm_hz":25000,"sink_duty_pct":35.5,"duration_ms":10000,"stimulus":"pwm","applied_sink_duty_pct":35.498,"duty_resolution_bits":11}
{"pwm_hz":25000,"sink_duty_pct":100.0,"duration_ms":10000,"stimulus":"static_sink","applied_sink_duty_pct":100.000}
```

`metrics` (`phase_end`, `run_complete`):

```json
{"tach_edges":2001,"window_start_us":81234567,"window_us":10000412,"edge_hz":200.091,"ppr":null,"rpm":null,"released_us":91235101}
```

- `window_start_us`, `window_us`, `released_us`: `esp_timer` microseconds since
  boot, the same clock as `uptime_ms`. The window opens after the stimulus is
  applied and the counter cleared, and closes after the final count read.
- `edge_hz = tach_edges / window`, averaged over the whole hold, transients
  included. It has ±1 edge of quantization.
- `ppr` and `rpm` are `null` unless PPR is configured with evidence.
- `fixture_error` appears for `invalid_parameters`, `pre_release_failed`,
  `tach_unavailable`, `actuation_failed`, `tach_clear_failed`,
  `tach_read_failed`, or `release_failed`.

### Identity and provenance

`/api/v1/device` reports `board_profile`, `experiment_profile`, `build`
(firmware version, git SHA, and source-tree state when the build could
establish them), and `device_id`. The boot event carries the same image
identity. `measurement_provenance` records that `fan_tach_edges` come from
`dut.esp32s3_pcnt`, that `fan_speed` is `external` unless PPR is configured
with evidence (then `derived.fan_tach_edges_and_configured_ppr`), and that fan
supply voltage and current, PWM-line waveform, airflow, and temperature are
`external`.

## Host sweep

`fan-sweep` runs one `FAN_PWM_HOLD` per step and writes machine-readable JSON.
Sweep logic lives only on the host.

```text
python -m cli.dragonbench --host <board> fan-sweep --pwm-hz <hz> \
  --low-pct <pct> --high-pct <pct> --step-pct <pct> \
  --order up|down|up-down|down-up --hold-ms <ms> [--gap-ms <ms>] --output sweep.json
```

- Order: `up` goes low → high and `down` goes high → low. `up-down` and
  `down-up` visit the turnaround point once. The far endpoint is always
  included, even when the step does not divide the range evenly.
- The sweep refuses a device whose `/api/v1/device` does not report
  `experiment_profile: fan-characterization`, before starting any run.
- The file is rewritten after every step. It records the device identity, the
  planned steps, and for each step the run ID, result, host timestamps,
  phase sequence numbers, and uptime, parameters, metrics, and any fault.
  `external_measurements` is `null`: attach scope, current, and optical data
  separately, with their own provenance.
- The sweep stops at the first step whose result is not `pass`. On a timeout,
  refusal, or Ctrl-C it aborts the active run (which releases the line) and
  writes `status: failed` or `interrupted` with the partial results.

`run FAN_PWM_HOLD --duration <s> --pwm-hz <hz> --sink-duty-pct <pct>` starts a
single hold.

## Known limitations

- **The line is released between sweep steps.** Each step is an independent
  run, so between steps the fan PWM line is released for the host round trip
  (tens to hundreds of milliseconds) plus `--gap-ms`. A downward sweep
  therefore does not hold a continuously running fan through decreasing duty.
  Minimum stable running duty and restart hysteresis
  (characterization plan §9) cannot be read from this sweep alone. Doing that
  would need a firmware-held multi-step primitive, which this slice
  deliberately leaves out.
- **Tach results are one whole-hold average.** There is no time series, first
  edge timestamp, jitter, or startup-latency measurement (plan §7, §9). Use the
  external logic analyzer or scope for those. Longer holds reduce how much of
  the average is transient.
- **Tach semantics are unverified.** Counting assumes one falling edge per
  tach pulse on a clean, conditioned signal. A noisy line needs the glitch
  filter and a scope check. Stopped or locked-rotor tach behavior (plan §10) is
  reported only as raw edges.
- Static gate drive, LEDC output, PCNT accumulation, pad readback, and the
  shutdown handler have been compiled but never run on hardware.
- Nothing here measures supply current, temperature, airflow, noise, or
  vibration (plan §11–13). Those stay with external instruments.

## Open items

These must come from the bench before any wiring or first power:

1. Board: TinyS3[D], N8R8, or N16R8 module for the fixture.
2. Gate GPIO and tach GPIO, chosen from free, non-reserved pins on that board.
   Check each pin's reset-state pull in the ESP32-S3 datasheet IO MUX table
   against the gate resistor.
3. Stage topology and part: MOSFET or BJT, inverting or not (sets
   `CONFIG_DB_FAN_GATE_SINK_LEVEL`), gate/base resistor, and a gate resistor to
   the release level sized to hold the stage off with the GPIO undriven.
4. Fan PWM-lead electrical limits and its internal pull-up (plan §6), and
   confirmation that the stage's voltage and current ratings cover them.
5. Tach output circuit, sink-current limit, the external 3.3 V pull-up value,
   and any series resistor or clamp that keeps the GPIO at or below 3.3 V
   (plan §7). Whether the internal pull-up is ever acceptable.
6. Lead identity on the delivered specimen (plan §3) and the common-ground
   arrangement between the 24 V supply and the ESP32-S3.
7. Glitch-filter setting after scoping the tach line, if one is needed.
8. PPR and the evidence establishing it, only after it has been measured.
