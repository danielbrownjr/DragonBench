# Rev 0 bring-up: minimum safe first power

Record every result in the JumpJet characterization evidence record, with the
instrument, its setting, and a photo or capture. Do the steps in order: each
one removes an unknown that the next depends on.

**Starting state**

- JP1, JP2, JP3, JP4 **OPEN**. JP5 fitted.
- F1 holds a labelled 0 Ω link or dummy fuse, not a rated fuse. The bench
  PSU current limit is the first protection.
- Controller not connected to J1. Fan not connected to J3.

**Operating rule (tach back-power)**

- The controller's 3V3 must be powered **before JP3 or JP4 is closed and
  before fan power is applied**.
- Remove 3V3 only after fan power is off.
- See README "Tach protection and back-power".

## 1. Identify the specimen

1. Photograph the label: part number `9GA0424P3J001`, lot, and date code.
2. Photograph each lead and record its colour.
3. Record any connector or housing on the leads.

## 2. Verify the leads before any 24 V

1. With the fan unpowered, measure lead-to-lead resistance and diode-mode
   readings. Record all of them.
2. Establish each lead's function by photo, continuity, and the manufacturer
   drawing (9GA0424P3J001 Rev C). The catalog colour convention is **not**
   sufficient on its own.
3. Do not land a lead on J3 until its function is established.
4. `FAN_PWM_RAW` must never reach `FAN_24V`: Q1 is not rated for that fault.

## 3. Prepare the bench supply

1. Set 24.0 V and a conservative current limit based on the 0.27 A rating.
   Record the limit. It is a bench setting, not a derived startup
   specification.
2. Check the output with no load.
3. Record whether the PSU output floats or is earth-bonded.
4. Connect J2 and confirm polarity at TP12 against TP14 **before** landing the
   fan. The fixture has no reverse-polarity element.

## 4. Fan power only, signal lines released

1. Land only `FAN_24V` and `FAN_GND` on J3. Keep the control and sensor leads
   insulated and off J3.
2. Power up. Record the supply current: the inrush peak, if a current probe
   is available, and the steady state.
3. The drawing specifies that an open control lead gives the same speed as
   100 % PWM. Record whether the specimen behaves that way.

## 5. FAN_PWM_RAW with no active drive

1. Land the control lead on J3.3. Keep JP2 open.
2. Scope TP6 against TP7. Record the open-circuit voltage (drawing: ≤ 5.25 V)
   and any waveform.
3. Briefly short TP6 to GND through a DMM on its mA range. Record:
   - the source current (drawing: ≤ 2 mA at 0 V)
   - the resulting speed (drawing: 0 % = stopped)
4. Close JP2 only if the voltage is ≤ 5.25 V and the current is ≤ 2 mA.

## 6. Raw tach, before any pull-up or GPIO

1. Power the controller's 3V3 now (operating rule), even if J1 is not yet
   fully wired.
2. Land the sensor lead on J3.4. Keep JP3 and JP4 open.
3. Scope TP8 with the fan running. The drawing's sensor specification
   9D0001H202 says open collector: expect TP8 to float or sit near 0 V with
   no pull-up.
4. **If TP8 is actively driven above 3.3 V, stop** and revise the tach stage.
5. Close **JP3** only. Record at TP8:
   - high level
   - low level, which must be ≤ ~0.6 V (the documented VCE(sat) max is
     0.8 V at 5 mA)
   - edge shape, glitches, and ringing
6. Add no filtering.

## 7. Validate the open-drain PWM stage

1. With the controller still off J1 and JP2 open, drive TP3 (`PWM_IN`) from
   a signal generator:
   - 0–3.3 V square wave
   - 25 kHz, the drawing's specified control frequency
2. Scope TP4 and TP5. Then close JP2 and scope TP6. Record:
   - the low level (≤ 0.4 V required, about 4 mV expected)
   - the edges
   - the duty cycle against the generator
3. Remove the generator.
4. Flash the fan-characterization image with the N8R8 bench overlay:
   - `GATE_GPIO=6`, `SINK_LEVEL=1`, `TACH_GPIO=7`
   - PPR 0, internal tach pull-up off
5. Wire J1 and close JP1.
6. Confirm the boot log shows the line released. Confirm TP4 stays at 0 V
   through reset, flashing, and a controller power cycle.
7. Run `FAN_PWM_HOLD` at 0 %, a mid duty, and 100 %. For each, compare the
   TP4/TP6 captures with the reported `applied_sink_duty_pct`.

## 8. Connect tach to GPIO7

1. Continue only if step 6 showed an open-collector output with levels
   within 0–3.3 V, and the controller's 3V3 is on.
2. Close JP4.
3. Check that TP9 (`TACH_GPIO`) follows TP8 within the R4/R5 divider:
   - high ≈ 3.09 V
   - low ≈ V(TP8)
4. Run a hold. Compare `tach_edges` and `edge_hz` with a scope or
   logic-analyzer count over the same window.
5. Add a glitch filter only if the captures show a need.

## 9. PPR stays unknown

The manufacturer documentation suggests 2 pulses per revolution. DragonBench
still keeps `CONFIG_DB_FAN_TACH_PPR=0` until independent evidence exists:
preferably an optical tachometer correlated with tach frequency at several
speeds on this specimen.

Record that evidence and reference it in `CONFIG_DB_FAN_TACH_PPR_EVIDENCE`
when PPR is set.

## After bring-up

- Choose F1 only after startup and locked-rotor current are measured.
  Locked-rotor is a separate, deliberate test with its own plan.
- Nothing measured on this fixture becomes a JumpJet threshold, frequency,
  PPR, or safety value without its own review.
