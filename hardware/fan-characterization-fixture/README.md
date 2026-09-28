# Fan-characterization fixture, Rev 0 (draft)

> **This is bench characterization hardware, not JumpJet production hardware.**
>
> The fixture lets DragonBench's `fan-characterization` experiment profile
> ([docs/FAN_CHARACTERIZATION.md](../../docs/FAN_CHARACTERIZATION.md)) drive a
> fan control input through an open-drain stage and count tach edges.
>
> It defines no JumpJet values: no GPIOs, thresholds, startup duty, stall
> limits, or fan-safety policy. The GPIOs named below are a bench wiring
> overlay only.

The DUT is the Sanyo Denki San Ace 40 `9GA0424P3J001`:

- 24 V, 40 × 40 × 28 mm
- 4-wire, PWM control with pulse sensor

## Files

| Path | Role |
|---|---|
| `generator/fixture.py` | **Source.** Parts, values, wiring, sheet notes, and title block. |
| `generator/build_schematic.py`, `generator/sexp.py` | Source. Turn `fixture.py` into the KiCad files. |
| `generator/expected-nets.txt` | Source. Hand-maintained expected connectivity, reviewed independently of `fixture.py`. |
| `generator/check_netlist.py` | Source. Compares KiCad's extracted netlist with `fixture.py` and `expected-nets.txt`, and checks the Rev 0 jumper defaults. |
| `verify.sh` | Regenerate and verify. See [Reproducing](#reproducing-and-verifying). |
| `fan-characterization-fixture.kicad_sch`, `.kicad_pro` | Generated. KiCad 9 schematic, one A3 sheet. No PCB yet. |
| `fan-characterization-fixture.pdf`, `.svg` | Generated review exports. |
| `BRINGUP.md` | Minimum safe first-power procedure. |

Do not edit the schematic in eeschema. Change `generator/fixture.py` and run
`./verify.sh --update`. A hand edit makes `./verify.sh` fail with `STALE`.

## Reproducing and verifying

Requirements: Docker. `verify.sh` runs everything inside one pinned image,
`kicad/kicad:9.0@sha256:e638b79b…`, which ships KiCad 9.0.9 and Python 3.11.
The generator therefore embeds exactly the symbol libraries that ERC checks
against.

```text
./verify.sh            # check only
./verify.sh --update   # rewrite .kicad_sch, .kicad_pro, .pdf, .svg, then check
```

The check does four things:

1. **Reproduces the schematic.** The checked-in `.kicad_sch` and `.kicad_pro`
   must match the generator output byte for byte. UUIDs are derived from
   content, so the output is deterministic.
2. **Runs ERC.** `kicad-cli sch erc --severity-all` must report 0 errors and
   0 warnings.
3. **Checks connectivity.** The netlist KiCad extracts must agree exactly
   with `fixture.py` and with `expected-nets.txt`.
4. **Checks jumper defaults.** JP1–JP4 must be `OPEN` and JP5 `FITTED`,
   read from each symbol's `Default` field.

The ERC report, extracted netlist, and fresh PDF/SVG are written to a
temporary directory. They are validation output, so none are committed.
The PDF and SVG exports are not compared byte for byte.

## Blocks

### 1. MCU / DragonBench interface (J1)

J1 carries abstract nets: `MCU_PWM`, `TACH_GPIO`, `3V3`, `GND`. The
controller supplies 3V3; the fixture never generates it.

### 2. PWM open-drain driver

- The gate path runs `MCU_PWM` → JP1 → R1 220 Ω → Q1 gate.
- R2 (10 kΩ) pulls the gate down.
- The Q1 drain goes → JP2 → `FAN_PWM_RAW`. The source goes to `GND`.

### 3. Tach input

`FAN_TACH_RAW` feeds two independently jumpered paths:

- **JP3:** enables the R3 10 kΩ pull-up to 3V3.
- **JP4:** feeds the protected path to the GPIO: R4 22 kΩ in series, then the
  D1 BAT54S clamp and R5 470 kΩ to GND, then `TACH_GPIO`.

C2 is a DNP footprint for a later glitch filter.

### 4. 24 V supply

- The supply path runs J2 → F1 → JP5 `I_MEAS` → `FAN_24V`.
  - F1 is a fuse holder whose rating is TBD.
  - JP5 is a link that an ammeter can replace.
- D2/R6 indicate 24 V present.
- C1 (bulk capacitor) is DNP.
- NT1/NT2 form the ground star.

### 5. Fan connector (J3)

J3 has one terminal per fan function: `FAN_24V`, `FAN_GND`, `FAN_PWM_RAW`,
`FAN_TACH_RAW`. These are fixture functions, not the fan's physical wire
order.

### 6. Test points and jumpers

The table is on the sheet. The Rev 0 defaults are JP1–JP4 **OPEN** and JP5
**FITTED**.

## Controller wiring overlay (local, not part of the fixture)

| J1 | Net | N8R8 breakout (bench overlay, provisional) | TinyS3[D] |
|---|---|---|---|
| 1 | `MCU_PWM` (out) | GPIO6 | own overlay, TBD |
| 2 | `TACH_GPIO` (in) | GPIO7 | own overlay, TBD |
| 3 | `3V3` | 3V3 terminal (**never 5V**) | 3V3 |
| 4 | `GND` | GND terminal | GND |

`sdkconfig.fan-characterization.local` for the N8R8 wiring:

```text
CONFIG_DB_FAN_PWM_GATE_GPIO=6
CONFIG_DB_FAN_GATE_SINK_LEVEL=1
CONFIG_DB_FAN_TACH_GPIO=7
# CONFIG_DB_FAN_TACH_INTERNAL_PULLUP is not set
# CONFIG_DB_FAN_TACH_PPR stays 0 (unknown)
```

Why GPIO6/7:

- **Not reserved.** They pass PR #8's `DB_FAN_PIN_RESERVED`: they are not
  strapping, USB, flash/PSRAM, Octal PSRAM (33–37), or UART0 pins, and not the
  TinyS3D RF switch (38).
- **No pull at reset.** They have no pull-up or pull-down at or after reset
  (ESP32-S3 datasheet, GPIO4–8), so R2 alone sets the gate before firmware
  runs.
- **Unused alternate functions.** Their other functions are ADC1, touch, and
  RTC GPIO, none of which DragonBench uses.
- **Power-up glitch.** The documented power-up glitch is to the low level,
  which is the release level here.

The ESP32-S3-DevKitC-1 guide lists both pins with no onboard function.
**Confirm on your N8R8 board** (CH343P bridge, possibly not an Espressif
DevKitC) that GPIO6/7 reach the breakout and drive nothing onboard.

These are bench choices, not product GPIO assignments.

## DUT electrical facts (manufacturer documentation)

Source: the Sanyo Denki specification drawing for **9GA0424P3J001, Rev C**,
and the sensor specification it references, **9D0001H202**. The values below
are transcribed from those documents. The documents themselves are not stored
in this repository.

**Control (PWM) input:**

- Specified PWM frequency: **25 kHz**. This is the manufacturer-specified
  control frequency for 9GA0424P3J001; bench characterization will still
  verify the specimen's behaviour.
- Open-collector or open-drain drive is supported.
- Control terminal **open** gives the same speed as 100 % PWM (full speed).
- **0 %** PWM means stopped.
- The open control-terminal voltage is ≤ 5.25 V.
- The terminal sources ≤ 2 mA when the control voltage is 0 V. It sinks
  ≤ 1 mA at 5.25 V; that applies only to a push-pull driver, not to this
  open-drain stage.
- Required low level: ≤ 0.4 V.

**Sensor (tach) output, per 9D0001H202:**

- Open collector.
- VCE ≤ 27.6 V.
- IC ≤ 5 mA.
- VCE(sat) ≤ 0.8 V.
- The documented waveform is consistent with two output cycles per
  revolution (two falling edges per revolution).

These describe the DUT. They are not JumpJet policy or thresholds.

**PPR:** the manufacturer documentation suggests **2 pulses/rev**.
DragonBench's configured PPR stays **`CONFIG_DB_FAN_TACH_PPR=0` (unknown)**.
The profile's evidence policy requires independent verification on the
specimen before a non-zero PPR is committed, preferably optical RPM
correlated with tach frequency.

## PWM stage calculations

Q1 is the onsemi **NTR4003NT1G** (SOT-23, G=1, S=2, D=3). Its guaranteed
RDS(on) is **2.0 Ω max at VGS 2.5 V** and 1.5 Ω max at VGS 4.0 V.
Threshold voltage is not used below as proof that Q1 switches.

**Normal stress:**

- VDS is at most the open control voltage, **≤ 5.25 V**.
- ID is at most the control-terminal source current, **≤ 2 mA**.
- Q1's 30 V rating covers this signal interface only. It is **not** a claim
  that Q1 survives `FAN_PWM_RAW` being landed on `FAN_24V`: the legitimate
  supply reaches 26.4 V, which leaves no margin for transients. Lead identity
  is verified before landing (BRINGUP step 2).

**Driven gate voltage:**

- The static gate load is R1 + R2 = 10.22 kΩ, so the pad sources 0.32 mA and
  sits essentially at VDD.
- VGS = VDD × 10 k/10.22 k = **3.23 V** at 3.3 V.
- At the 3.0 V bottom of the ESP32-S3's recommended supply range it is
  **2.94 V**.
- Both exceed the 2.5 V point at which RDS(on) is guaranteed.
- Using the datasheet's worst VOH instead (0.8 × VDD, specified at
  full-strength output current, not at 0.32 mA) gives 2.58 V at a 3.3 V rail.
  That is still above 2.5 V.

**Gate current transient:**

- Peak charge current is ≤ 3.3 V / 220 Ω = **15 mA**. The GPIO's own output
  resistance makes it lower.
- Gate RC is 220 Ω × Ciss. It stays under 25 ns even for 100 pF, against a
  20 µs half-period at 25 kHz.

**FAN_PWM_RAW low level:**

- Worst case is 2 mA × 2.0 Ω = **4 mV**, far below the ≤ 0.4 V requirement.
- RDS(on) could be 200 Ω before the 0.4 V limit was reached.

**Released (GPIO Hi-Z, reset, flashing, or unpowered):**

- R2 holds the gate at IGSS × 10 kΩ, **≤ 0.1 V** at IGSS ≤ 10 µA. IGSS is
  assumed; confirm it from the datasheet.
- A stray 45 kΩ internal pull-up, which the firmware never enables, would
  give 3.3 × 10/55 = 0.6 V.
- The released state is confirmed on the scope at TP4/TP6 during bring-up,
  not inferred from VGS(th).

**What the stage omits:** no RC filter and no fixture pull-up on
`FAN_PWM_RAW`. The fan's internal pull-up sets the high level and edge rate.

## Tach protection and back-power

The tach output is documented as open collector. In normal operation it only
sinks, so it cannot back-power the 3V3 rail even while the controller is off.
Back-power needs a **fault**, such as the sensor lead landed on or shorted to
the fan supply (≤ 26.4 V).

With R4 = 22 kΩ, worst-case current into 3V3 with the controller unpowered
(rail near 0 V) is:

| Path | Needs | Worst-case current |
|---|---|---|
| R4 → D1 upper diode → 3V3 | JP4 closed | (26.4 − 0.35) V / 22 kΩ = **1.2 mA** |
| R3 → 3V3 | JP3 closed | 26.4 V / 10 kΩ = **2.7 mA** (2.64) |
| Both | JP3 and JP4 closed | **3.9 mA** |

With the controller powered, the same fault injects slightly less, and the
running ESP32 board draws tens of mA, so the rail cannot be pushed up.

Resistor dissipation in that fault is 32 mW in R4 and 70 mW in R3, within
0805 ratings.

**Decision:** keep the simple BAT54S clamp topology (option A), and make two
changes:

1. **R4 raised from 4.7 kΩ to 22 kΩ.** This cuts clamp injection from about
   5.5 mA to 1.2 mA and costs nothing in signal terms:
   - High level with JP3 and JP4 closed is 3.3 × 492/502 × 470/492 ≈
     **3.09 V**, above VIH 2.475 V.
   - RC with about 12 pF of pin and clamp capacitance is about 0.26 µs,
     negligible at tach rates.
2. **An explicit bench operating rule.** The controller's 3V3 must be
   **powered before JP3 or JP4 is closed and before fan power is applied**,
   and removed only after fan power is off. This rule is on the sheet and in
   BRINGUP.md.

The R3 path in particular is not limited by R4. Its value stays 10 kΩ, as
required for the pull-up.

Blocking diodes or a separate protected rail were not added. For a jumpered
bench fixture the rule and the reduced current are simpler and adequate.

**Tach signal margins:**

- The pull-up draws 3.3 V/10 kΩ = **0.33 mA**, far below IC ≤ 5 mA.
- Low level at the GPIO is ≤ 0.8 × 470/492 = **0.76 V** at the documented
  VCE(sat) max. VIL is 0.825 V, so the worst-case margin is only 61 mV.
- VCE(sat) is specified at the full 5 mA. At 0.33 mA it should be much
  lower, but bring-up must measure it: **V(TP8) low ≤ ~0.6 V**.
- There is no glitch filter in Rev 0. Keep `CONFIG_DB_FAN_TACH_INTERNAL_PULLUP`
  off.

## Ground topology

BENCH_GND at J2.2 is the only place where power return and signal reference
meet.

- **NT1** ties it to `FAN_GND`, which carries fan supply return only.
- **NT2** ties it to `GND`, which carries:
  - the Q1 source
  - the tach clamp and pulldowns
  - J1.4 (controller ground)
  - the scope ground

Fan motor current never flows in `GND`. The ≤ 2 mA control and tach currents
return through the star. The controller's USB ground meets the PSU negative
only there. Use a floating PSU output, or record the earth bond if there is
one.

## BOM

Status key:

- **FINAL:** justified by the function.
- **PROVISIONAL:** reasoned, but depends on a checkable assumption or on
  supply availability.
- **DNP/TBD:** footprint only, or value undecided.

| Ref | Part / value | Function | Stress | Why | Status |
|---|---|---|---|---|---|
| J1 | 4-pos 5.08 mm screw terminal | Controller link | 3.3 V, < 20 mA | Matches the screw-terminal breakout | PROVISIONAL (style) |
| JP1 | 2-pin header + shunt, `GATE_EN` | Disconnects the controller from the gate; TP3 can take a signal generator | 3.3 V | Isolation point | FINAL |
| R1 | 220 Ω 1 % 0805 | Gate series resistor | ≤ 15 mA peak | See calculations | PROVISIONAL (until Ciss confirmed) |
| R2 | 10 kΩ 1 % 0805 | Gate pulldown | 0.32 mA | Holds Q1 off when the GPIO is Hi-Z/reset/unpowered | PROVISIONAL (confirm IGSS) |
| Q1 | onsemi NTR4003NT1G, SOT-23 | Open-drain sink on the fan control input | VDS ≤ 5.25 V, ID ≤ 2 mA | RDS(on) guaranteed at VGS 2.5 V; ESD-protected gate. Signal interface only, not a 24 V miswire device. | PROVISIONAL (datasheet values below) |
| JP2 | 2-pin header + shunt, `PWM_LINE_EN` | Fully releases `FAN_PWM_RAW` | ≤ 5.25 V | Isolation point | FINAL |
| JP3 | 2-pin header + shunt, `TACH_PU_EN` | Enables the tach pull-up | 3.3 V | Default open | FINAL |
| R3 | 10 kΩ 1 % 0805 | Tach pull-up to 3V3 | 0.33 mA | Far below IC 5 mA; about 1 µs rise with 100 pF | PROVISIONAL |
| JP4 | 2-pin header + shunt, `TACH_GPIO_EN` | Connects raw tach to the protected GPIO path | ≤ raw tach | Default open, so TP8 is unloaded | FINAL |
| R4 | 22 kΩ 1 % 0805 | Series protection | 1.2 mA / 32 mW at a 26.4 V fault | Limits clamp back-power | PROVISIONAL |
| D1 | BAT54S, SOT-23 | Clamps `TACH_GPIO` to GND/3V3 | ≤ 1.2 mA fault | ESP32-S3 inputs are not 5 V tolerant | PROVISIONAL |
| R5 | 470 kΩ 1 % 0805 | Holds `TACH_GPIO` low with JP4 open | µA | Stops PCNT counting a floating input | PROVISIONAL |
| C2 | 0805, **DNP** | Future glitch filter | – | Rev 0 observes the unfiltered waveform | DNP/TBD |
| J2 | 2-pos 5.08 mm screw terminal | Bench PSU input | 24 V, current TBD | – | PROVISIONAL (rating vs locked-rotor) |
| F1 | 5 × 20 mm clip holder, **element TBD** | Supply fuse | TBD | No rating until startup and locked-rotor current are measured. The PSU current limit is the first protection during characterization. | DNP/TBD |
| JP5 | 2-pin header + shunt, `I_MEAS`, **fitted** | Break for a series ammeter | fan current (TBD) | Current measurement without rewiring | PROVISIONAL (shunt rating vs locked-rotor) |
| R6 | 10 kΩ 1 % 0805 | LED current limit | 2.2 mA, 48 mW | – | PROVISIONAL |
| D2 | green LED 0805 | 24 V present | 2.2 mA | Upstream of JP5, so it is out of the fan current | PROVISIONAL |
| C1 | electrolytic ≥ 50 V, 6.3 mm radial, **DNP** | Bulk decoupling at the fan | – | Only for a measured need; fitting it changes the supply-current waveform | DNP/TBD |
| NT1, NT2 | net ties | Ground star | – | Enforces the topology | FINAL |
| J3 | 4-pos 5.08 mm screw terminal | DUT leads by verified function | 24 V / ≤ 5.25 V / tach | Terminal order is the fixture's own; the fan's wire order is not assumed | PROVISIONAL (style) |
| TP1–TP14 | Keystone 5000-series loops | Probe points | – | See the sheet | FINAL |

Confirm the NTR4003N datasheet values before ordering. The session that drew
this could not reach vendor PDFs, so these came from summaries of onsemi's
datasheet:

- VDS 30 V
- RDS(on) 2.0 Ω max at 2.5 V
- ESD-protected gate
- SOT-23 pinout
- IGSS
- Ciss

## FR120N module: not used

The FR120N optocoupler/power-MOSFET module is original Jetpack power-switch
hardware. Its topology has not been verified well enough for use on a fan
control line, so it is not part of this fixture.

It is reserved for later power-switch or heater-load characterization. Only
one module survives: it is not to be modified, opened, depotted, or
destructively characterized as part of this work.

## Specimen facts still to verify

1. Specimen identity, and lead colours and functions. Verify by photo,
   continuity, and the manufacturer drawing. The colour convention (red +,
   black −, brown PWM, yellow sensor) is a **catalog convention, not yet
   verified on the specimen**.
2. Specimen behaviour on the control lead:
   - open-circuit voltage
   - source current into 0 V
   - full speed with the lead open
   - stop at 0 %
   - response at 25 kHz
3. Specimen tach:
   - open-collector behaviour
   - low level at 0.33 mA (must be ≤ ~0.6 V at TP8)
   - edge quality
4. Startup, running, and locked-rotor current at 24 V. These set the ratings
   of F1, JP5, and J2.
5. PPR by optical RPM, or other independent evidence, correlated with tach
   frequency. Until then `CONFIG_DB_FAN_TACH_PPR=0`.
6. Whether a glitch filter (C2 and/or `CONFIG_DB_FAN_TACH_GLITCH_FILTER_NS`)
   is needed. Decide from scope captures.
7. Q1 datasheet values: IGSS, Ciss, and pinout.
