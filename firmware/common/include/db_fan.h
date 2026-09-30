#pragma once

// Bench-only fan-characterization fixture: a PWM stimulus through an external
// open-drain transistor stage and tach edge capture. This is characterization
// equipment, not product fan control: no closed loop, no thresholds, no fan
// safety policy. Tach readings never feed back into the stimulus.
//
// Everything here is platform-neutral so the stimulus lifecycle and the tach
// arithmetic are testable on a host. GPIO and peripheral access lives only in
// firmware/main/fan_characterization.c, behind db_fan_ops_t,
// and is compiled only into the fan-characterization experiment profile.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "db_experiment.h"

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

// sink_duty_pct is the fraction of time the external stage sinks the fan PWM
// line. The endpoints are static gate levels, not PWM: 0 % holds the stage off
// (released) and 100 % holds it on. LEDC is used only strictly between them,
// which also keeps the compare value inside 1..2^bits-1 (ESP32-S3 LEDC must not
// be given 2^duty_resolution).
typedef enum {
    DB_FAN_STIMULUS_STATIC_RELEASE,
    DB_FAN_STIMULUS_PWM,
    DB_FAN_STIMULUS_STATIC_SINK,
} db_fan_stimulus_mode_t;

typedef struct {
    db_fan_stimulus_mode_t mode;
    uint32_t resolution_bits;   // PWM only, else 0
    uint32_t duty_counts;       // PWM only: LEDC high-time counts, 1..2^bits-1
    uint32_t applied_milli_pct; // sink duty actually produced, 0..100000
} db_fan_stimulus_t;

const char *db_fan_stimulus_mode_name(db_fan_stimulus_mode_t mode);
bool db_fan_pwm_hz_valid(uint32_t pwm_hz);
bool db_fan_sink_duty_valid(uint16_t sink_duty_tenths_pct);
// Converts a JSON number to tenths of a percent; false unless it is 0..100 in
// 0.1 steps.
bool db_fan_sink_duty_from_pct(double sink_duty_pct, uint16_t *tenths_out);
bool db_fan_stimulus_plan(uint32_t pwm_hz, uint16_t sink_duty_tenths_pct, db_fan_stimulus_t *stimulus);

// Tach arithmetic. Edge frequency is edges per second over the capture window;
// false when the window is empty. RPM needs an explicitly configured PPR:
// db_fan_rpm_milli returns false for ppr == 0 (unknown).
bool db_fan_edge_hz_milli(int64_t edge_count, int64_t window_us, uint64_t *hz_milli);
bool db_fan_rpm_milli(int64_t edge_count, int64_t window_us, uint32_t ppr, uint64_t *rpm_milli);

// Hardware seam, in pad terms only. Which gate level sinks is decided here in
// the common layer from gate_sink_level, so both stage polarities are testable.
//   drive_static: route the pad to a plain GPIO output at gate_level and verify
//                 it by readback; detaches any PWM. Safe to call at any time.
//   start_pwm:    LEDC at pwm_hz with duty_counts high-time out of 2^bits;
//                 invert_output makes the high-time drive the pad low.
//   tach_ready:   capture path configured and usable; no side effects.
typedef struct {
    bool (*drive_static)(void *ctx, int gate_level);
    bool (*start_pwm)(void *ctx, uint32_t pwm_hz, uint32_t resolution_bits, uint32_t duty_counts,
                      bool invert_output);
    bool (*tach_ready)(void *ctx);
    bool (*tach_clear)(void *ctx);
    bool (*tach_read)(void *ctx, int64_t *edge_count);
    int64_t (*now_us)(void *ctx);
    bool (*should_abort)(void *ctx);
    void (*sleep_ms)(void *ctx, uint32_t ms);
    void *ctx;
} db_fan_ops_t;

typedef struct {
    const db_fan_ops_t *ops;
    int gate_sink_level; // 0 or 1: gate level at which the external stage sinks
} db_fan_fixture_t;

int db_fan_release_level(const db_fan_fixture_t *fixture);

typedef enum { DB_FAN_HOLD_PASS, DB_FAN_HOLD_ABORTED, DB_FAN_HOLD_FAIL } db_fan_hold_outcome_t;

typedef struct {
    db_fan_stimulus_t stimulus;
    int64_t window_start_us;
    int64_t window_end_us;
    int64_t released_us;
    int64_t edge_count;
    bool tach_valid;
    bool actuated; // a stimulus other than release was driven
    bool released;
    const char *error; // failing stage, or NULL
} db_fan_hold_result_t;

// Drives the release level and verifies it. Used at boot and on every exit.
bool db_fan_release(const db_fan_fixture_t *fixture);

// One FAN_PWM_HOLD: plan, release, confirm tach readiness, then actuate the
// planned stimulus, clear the counter and open the window, hold, read, and
// release on every exit path (end, abort, and each failure). Nothing is
// actuated unless the line was released and tach capture is ready.
db_fan_hold_outcome_t db_fan_hold(const db_fan_fixture_t *fixture, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                                  uint32_t duration_ms, db_fan_hold_result_t *result);

bool db_fan_format_parameters(char *out, size_t out_len, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                              uint32_t duration_ms, const db_fan_stimulus_t *stimulus);
bool db_fan_format_metrics(char *out, size_t out_len, const db_fan_hold_result_t *result, uint32_t ppr);
