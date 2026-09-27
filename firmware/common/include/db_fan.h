#pragma once

// Bench-only fan-characterization fixture: a PWM stimulus through an external
// open-drain transistor stage and tach edge capture. This is characterization
// equipment, not product fan control: no closed loop, no thresholds, no fan
// safety policy. Tach readings never feed back into the stimulus.
//
// Everything here is platform-neutral so the stimulus lifecycle and the tach
// arithmetic are testable on a host. GPIO and peripheral access lives only in
// firmware/targets/esp32s3/main/fan_fixture.c, behind db_fan_ops_t.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#if defined(ESP_PLATFORM)
#include "sdkconfig.h"
#endif

// Normal profiles leave CONFIG_DB_FAN_FIXTURE unset; only the fan-fixture
// overlay (sdkconfig.defaults.fanfixture) turns the stimulus on.
#if defined(CONFIG_DB_FAN_FIXTURE) && CONFIG_DB_FAN_FIXTURE
#define DB_FAN_FIXTURE_BUILD 1
#else
#define DB_FAN_FIXTURE_BUILD 0
#endif

// Fixture generator limits, not fan specifications. The upper bound keeps at
// least DB_FAN_MIN_RESOLUTION_BITS of duty resolution (0.1 % steps) from the
// 80 MHz LEDC source; the lower bound stays inside the LEDC divider range at
// the maximum 14-bit resolution.
#define DB_FAN_PWM_HZ_MIN 10U
#define DB_FAN_PWM_HZ_MAX 50000U
#define DB_FAN_SINK_DUTY_TENTHS_MAX 1000U
#define DB_FAN_LEDC_SOURCE_HZ 80000000U
#define DB_FAN_MIN_RESOLUTION_BITS 10U
#define DB_FAN_MAX_RESOLUTION_BITS 14U
#define DB_FAN_LEDC_DIVIDER_MAX_X256 ((1024U * 256U) - 1U)
#define DB_FAN_TACH_PPR_MAX 16U
#define DB_FAN_ABORT_POLL_MS 20U

// ESP32-S3 pins a fixture signal must never use: strapping pins (0, 3, 45, 46),
// USB D-/D+ (19, 20), pins that do not exist (22-25), in-package/SPI flash and
// PSRAM (26-32), the Octal PSRAM data pins (33-37) on octal profiles, and the
// UART0 console (43, 44). This only excludes pins known to be taken; it does
// not choose one. Usable from #if so a bad assignment fails the build.
#define DB_FAN_PIN_RESERVED(gpio, octal_psram)                                        \
    ((gpio) < 0 || (gpio) > 48 || (gpio) == 0 || (gpio) == 3 || (gpio) == 45 ||         \
     (gpio) == 46 || (gpio) == 19 || (gpio) == 20 || ((gpio) >= 22 && (gpio) <= 32) ||  \
     ((octal_psram) && (gpio) >= 33 && (gpio) <= 37) || (gpio) == 43 || (gpio) == 44)

// Parameters and metrics must fit one DB_EVENT_JSON_LEN event envelope.
#define DB_FAN_PARAMETERS_JSON_LEN 160
#define DB_FAN_METRICS_JSON_LEN 256

typedef struct {
    uint32_t resolution_bits;
    uint32_t duty_counts;       // LEDC compare value, 0..2^resolution_bits
    uint32_t applied_milli_pct; // sink duty actually programmed, 0..100000
} db_fan_pwm_plan_t;

bool db_fan_pwm_hz_valid(uint32_t pwm_hz);
bool db_fan_sink_duty_valid(uint16_t sink_duty_tenths_pct);
// Converts a JSON number to tenths of a percent; false unless it is 0..100 in
// 0.1 steps.
bool db_fan_sink_duty_from_pct(double sink_duty_pct, uint16_t *tenths_out);
bool db_fan_pwm_plan(uint32_t pwm_hz, uint16_t sink_duty_tenths_pct, db_fan_pwm_plan_t *plan);

// Tach arithmetic. Edge frequency is edges per second over the capture window;
// false when the window is empty. RPM needs an explicitly configured PPR:
// db_fan_rpm_milli returns false for ppr == 0 (unknown).
bool db_fan_edge_hz_milli(int64_t edge_count, int64_t window_us, uint64_t *hz_milli);
bool db_fan_rpm_milli(int64_t edge_count, int64_t window_us, uint32_t ppr, uint64_t *rpm_milli);

// Hardware seam. release() must drive the gate to the level that turns the
// external stage off and verify it; it must be safe to call at any time.
typedef struct {
    bool (*release)(void *ctx);
    bool (*apply)(void *ctx, uint32_t pwm_hz, const db_fan_pwm_plan_t *plan);
    bool (*tach_clear)(void *ctx);
    bool (*tach_read)(void *ctx, int64_t *edge_count);
    int64_t (*now_us)(void *ctx);
    bool (*should_abort)(void *ctx);
    void (*sleep_ms)(void *ctx, uint32_t ms);
    void *ctx;
} db_fan_ops_t;

typedef enum { DB_FAN_HOLD_PASS, DB_FAN_HOLD_ABORTED, DB_FAN_HOLD_FAIL } db_fan_hold_outcome_t;

typedef struct {
    db_fan_pwm_plan_t plan;
    int64_t window_start_us;
    int64_t window_end_us;
    int64_t released_us;
    int64_t edge_count;
    bool tach_valid;
    bool released;
    const char *error; // failing stage, or NULL
} db_fan_hold_result_t;

// Boot/default state: release the line before anything else runs.
bool db_fan_boot_release(const db_fan_ops_t *ops);

// One FAN_PWM_HOLD: release, program the stimulus, capture tach for the hold,
// then release on every exit path (end, abort, and each failure).
db_fan_hold_outcome_t db_fan_hold(const db_fan_ops_t *ops, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                                  uint32_t duration_ms, db_fan_hold_result_t *result);

bool db_fan_format_parameters(char *out, size_t out_len, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                              uint32_t duration_ms, const db_fan_pwm_plan_t *plan);
bool db_fan_format_metrics(char *out, size_t out_len, const db_fan_hold_result_t *result, uint32_t ppr);
