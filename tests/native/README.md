# Native common-state test

`test_db_run.c` directly exercises the platform-neutral C workload registry,
validation, state transitions, run identity retention, and abort behavior.
`test_db_fan.c` covers the fan-characterization logic: parameter bounds, the
static-release / PWM / static-sink stimulus plan, the sink fraction the line
sees for both gate polarities, tach readiness before actuation, tach
edge-frequency and RPM arithmetic, unknown PPR, the event-size budget, and
release of the stimulus line on boot, run end, abort, and every error path.
Both are built twice: as the baseline experiment profile and with
`-DCONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION=1`.

From the repository root on a host with a C11 compiler:

```text
for defines in "" "-DCONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION=1"; do
  for test in test_db_run test_db_fan; do
    cc -std=c11 -Wall -Wextra -Werror $defines -Ifirmware/common/include \
      firmware/common/db_run.c firmware/common/db_network.c firmware/common/db_fan.c \
      tests/native/$test.c -o $test && ./$test
  done
done
```

The generated executable is ignored by Git.
