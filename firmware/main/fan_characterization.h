#pragma once

// ESP32-S3 backend of the fan-characterization experiment profile: bench-only
// stimulus and tach capture. Compiled only when that profile is selected;
// baseline contains none of it.

#include "db_fan.h"
#include "db_run.h"

#if DB_EXPERIMENT_FAN_CHARACTERIZATION
#include "cJSON.h"

// Drives the stimulus gate to its release level, then prepares tach capture.
// Call first in app_main, before anything that could delay it.
void fan_characterization_boot(void);

db_fan_hold_outcome_t fan_characterization_hold(const db_run_request_t *request, bool (*should_abort)(void),
                                       db_fan_hold_result_t *result);

// Tach capture configured and readable; required before any FAN_PWM_HOLD.
bool fan_characterization_tach_ready(void);

// Configured pulses per revolution; 0 means unknown and RPM is never derived.
uint32_t fan_characterization_ppr(void);

// Adds the static fixture configuration and live line state to a device object.
void fan_characterization_describe(cJSON *parent);
#endif
