# Bench workflow

1. Connect external supply and measurement equipment using the bench-approved
   fixture. DragonBench does not control the PSU.
2. Capture PSU/input voltage, relevant board rails, path current, and reset line
   externally. Do not enter those readings as DUT sensor values.
3. Discover the DUT or select its hostname/IP, then record `/api/v1/device`,
   `/api/v1/sensors`, and reset reason.
4. Start one workload at a time. Correlate `phase_start` and `phase_end` sequence
   markers with scope/current-logger time.
5. Export the run and external measurements together, keeping their provenance
   distinct.

The board's status RGB LED is solid green while the DUT is ready and idle and
is turned off before a run's `phase_start`, so it is dark for the whole
`phase_start`–`phase_end` window (and unpowered on the TinyS3[D]). It turns
green again only after a run passes. Green outside a run is load on the
module supply: do not use readings from between runs as baseline. See the
target profiles for each board's LED.

The host/operator owns voltage sweeps. Firmware contains no voltage thresholds
or electrical pass/fail limits. `OTA_PARTITION_WRITE` erases, writes, and verifies
only an inactive OTA slot; it never selects that slot for boot. Controlled reboot
is single-shot and never forms a reboot loop.

Record `/api/v1/device` with every capture: it names the board profile,
experiment profile, build revision, and device, and its
`measurement_provenance` says which quantities DragonBench measures and which
the bench must supply.

On a `fan-characterization` image, `FAN_PWM_HOLD` and the host `fan-sweep`
command provide the stimulus and raw tach counts. Wiring, semantics, and limits
are in [fan characterization](FAN_CHARACTERIZATION.md). Fan supply current, PWM-line and tach waveforms,
optical RPM, temperature, and airflow remain external evidence.

Recommended external fields are PSU/input voltage, `+5V_SYS_GATE`,
`+5V_MCU_FEED`, `+5V_MCU`, average/peak current, minimum rail voltage, reset or
brownout occurrence, and Wi-Fi disconnect/reconnect.
