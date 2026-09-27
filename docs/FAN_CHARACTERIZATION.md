# Bench fan-characterization fixture

> **BENCH CHARACTERIZATION EQUIPMENT — NOT PRODUCT FAN CONTROL.** This profile
> drives only the gate of an external open-drain stage and counts tach edges.
> It has no closed loop, no thresholds, no heater, and no fan-safety policy.
> `heater_capability` and `fan_control_capability` remain `false`.

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
| `CONFIG_DB_FAN_FIXTURE` profile, off in every normal profile | `Kconfig.projbuild`, `sdkconfig.defaults.fanfixture` |
| `FAN_PWM_HOLD` workload | `firmware/common/db_run.c` (registry, validation) |
| Stimulus lifecycle and tach arithmetic, host-tested | `firmware/common/db_fan.c` |
| LEDC stimulus and PCNT tach capture | `firmware/targets/esp32s3/main/fan_fixture.c` |
| `fan-sweep` host command | `cli/dragonbench/main.py` |

Normal builds report `FAN_PWM_HOLD` as `unsupported` (reason `requires
fan-fixture build`), reject it with HTTP 400, and link no LEDC, PCNT, or
fixture code. CI checks that absence in the ELF.

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
- **`sink_duty_pct`** is the percentage of each PWM period during which the
  external stage conducts and pulls the fan PWM line low. It is an electrical
  quantity. How the fan responds to it, including at 0 % and 100 %, is what the
  bench is there to measure.
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
| Boot | `fan_fixture_boot()` is the first statement of `app_main`. It drives the release level and reads the pad back. |
| Run start | `db_fan_hold` releases and verifies the line before it programs any stimulus. If it cannot, no stimulus is applied. |
| Run end, abort, and every error | `db_fan_hold` has one exit path, which releases and verifies the line. |
| `esp_restart` (including `CONTROLLED_REBOOT`) | Shutdown handler releases the line. |

To release, the firmware writes the release level to the output register, then
moves the pad from LEDC back to a plain GPIO output, so the switch cannot
glitch toward sink. Verification reads back the **pad** level. It does not
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

Create an untracked `sdkconfig.fanfixture.local` (ignored by Git) stating the
wired fixture:

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

Build, with the board overlay first:

```text
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.tinys3d;sdkconfig.defaults.fanfixture;sdkconfig.fanfixture.local" build
# or, with the same checks CI uses:
bash ci/build-esp32s3.sh tinys3d fanfixture
```

Delete a generated `sdkconfig` before switching between fixture and normal
profiles. At boot the serial log prints a `BENCH FAN FIXTURE BUILD` warning with
the configured pins and line state.

## FAN_PWM_HOLD

```text
POST /api/v1/runs
{"workload": "FAN_PWM_HOLD", "pwm_hz": <int>, "sink_duty_pct": <number>, "duration_ms": <int>}
```

| Parameter | Accepted | Notes |
|---|---|---|
| `pwm_hz` | integer 10–50000 | Limits of the fixture generator, not a fan specification. They keep at least 10-bit duty resolution from the 80 MHz LEDC clock. |
| `sink_duty_pct` | 0–100 in 0.1 steps | Quantized to the LEDC resolution; the programmed value is reported. |
| `duration_ms` | integer 1–3600000, required | No implied default for a stimulus. |

All three are required and validated on the device. `pwm_hz` or
`sink_duty_pct` on any other workload is rejected. A hold runs as follows:
release, program LEDC, clear the tach counter, start the window, hold (checking
for abort every 20 ms), read the tach count, end the window, release. Only one
run is active at a time.

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
{"pwm_hz":25000,"sink_duty_pct":35.5,"duration_ms":10000,"applied_sink_duty_pct":35.498,"duty_resolution_bits":11}
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
  `apply_failed`, `tach_clear_failed`, `tach_read_failed`, or `release_failed`.

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
  `bench_stimulus.fan_pwm_fixture: true`, before starting any run.
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
- LEDC output, PCNT accumulation, pad readback, and the shutdown handler have
  been compiled but never run on hardware.
- Nothing here measures supply current, temperature, airflow, noise, or
  vibration (plan §11–13). Those stay with external instruments.

## Open items

These must come from the bench before any wiring or first power:

1. Board: TinyS3[D] or N8R8 module for the fixture.
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
