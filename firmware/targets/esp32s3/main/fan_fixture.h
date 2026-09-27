#pragma once

// ESP32-S3 backend for the bench-only fan-characterization fixture. Compiled
// only when CONFIG_DB_FAN_FIXTURE is set; normal profiles contain none of it.

#include "db_fan.h"
#include "db_run.h"

#if DB_FAN_FIXTURE_BUILD
#include "cJSON.h"

// Drives the stimulus gate to its release level, then prepares tach capture.
// Call first in app_main, before anything that could delay it.
void fan_fixture_boot(void);

db_fan_hold_outcome_t fan_fixture_hold(const db_run_request_t *request, bool (*should_abort)(void),
                                       db_fan_hold_result_t *result);

// Configured pulses per revolution; 0 means unknown and RPM is never derived.
uint32_t fan_fixture_ppr(void);

// Adds the static fixture configuration and live line state to a device object.
void fan_fixture_describe(cJSON *parent);
#endif
