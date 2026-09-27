// Fan-fixture common logic. Built twice: as a normal profile, and with
// -DCONFIG_DB_FAN_FIXTURE=1 as the bench fixture profile.

#include "db_fan.h"
#include "db_run.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef enum { LINE_UNKNOWN, LINE_RELEASED, LINE_DRIVEN } fake_line_t;

typedef struct {
    fake_line_t line;
    int64_t clock_us;
    int release_calls;
    int apply_calls;
    int abort_after_polls; // <0: never
    int polls;
    int failing_release_call;
    bool fail_apply;
    bool fail_tach_clear;
    bool fail_tach_read;
    int64_t tach_edges_per_ms;
    int64_t tach_origin_us;
    uint32_t applied_hz;
    db_fan_pwm_plan_t applied_plan;
} fake_fixture_t;

static bool fake_release(void *ctx) {
    fake_fixture_t *fake = ctx;
    ++fake->release_calls;
    if (fake->failing_release_call == fake->release_calls) return false;
    fake->line = LINE_RELEASED;
    return true;
}

static bool fake_apply(void *ctx, uint32_t pwm_hz, const db_fan_pwm_plan_t *plan) {
    fake_fixture_t *fake = ctx;
    ++fake->apply_calls;
    if (fake->fail_apply) {
        fake->line = LINE_DRIVEN; // a partial configuration may already drive the pad
        return false;
    }
    fake->applied_hz = pwm_hz;
    fake->applied_plan = *plan;
    fake->line = LINE_DRIVEN;
    return true;
}

static bool fake_tach_clear(void *ctx) {
    fake_fixture_t *fake = ctx;
    fake->tach_origin_us = fake->clock_us;
    return !fake->fail_tach_clear;
}

static bool fake_tach_read(void *ctx, int64_t *edges) {
    fake_fixture_t *fake = ctx;
    if (fake->fail_tach_read) return false;
    *edges = (fake->clock_us - fake->tach_origin_us) / 1000 * fake->tach_edges_per_ms;
    return true;
}

static int64_t fake_now(void *ctx) { return ((fake_fixture_t *)ctx)->clock_us; }

static bool fake_should_abort(void *ctx) {
    fake_fixture_t *fake = ctx;
    return fake->abort_after_polls >= 0 && fake->polls++ >= fake->abort_after_polls;
}

static void fake_sleep(void *ctx, uint32_t ms) { ((fake_fixture_t *)ctx)->clock_us += (int64_t)ms * 1000; }

static db_fan_ops_t fake_ops(fake_fixture_t *fake) {
    memset(fake, 0, sizeof(*fake));
    fake->abort_after_polls = -1;
    fake->clock_us = 5000000;
    return (db_fan_ops_t){fake_release, fake_apply, fake_tach_clear, fake_tach_read, fake_now,
                          fake_should_abort, fake_sleep, fake};
}

static db_run_request_t fan_request(uint32_t pwm_hz, uint16_t tenths, uint32_t duration_ms) {
    db_run_request_t request = {.workload = DB_FAN_PWM_HOLD, .duration_ms = duration_ms};
    request.pwm_hz_set = request.sink_duty_set = true;
    request.pwm_hz = pwm_hz;
    request.sink_duty_tenths_pct = tenths;
    return request;
}

static void test_capability_gate(void) {
    char error[96];
    db_workload_t workload = DB_WORKLOAD_COUNT;
    assert(db_workload_parse("FAN_PWM_HOLD", &workload) && workload == DB_FAN_PWM_HOLD);
    assert(db_workload_supported(DB_FAN_PWM_HOLD) == (DB_FAN_FIXTURE_BUILD == 1));
    db_run_request_t request = fan_request(25000, 500, 1000);
#if DB_FAN_FIXTURE_BUILD
    assert(db_request_validate(&request, error, sizeof(error)));
#else
    assert(!db_request_validate(&request, error, sizeof(error)));
    assert(strcmp(error, "FAN_PWM_HOLD requires a fan-fixture build") == 0);
    // Every other workload stays available in a normal profile.
    for (int i = 0; i < DB_WORKLOAD_COUNT; ++i)
        assert(db_workload_supported((db_workload_t)i) == (i != DB_FAN_PWM_HOLD));
#endif
    // Fan parameters never ride along on another workload, in either build.
    db_run_request_t cpu = {.workload = DB_CPU_STRESS, .duration_ms = 1000, .pwm_hz_set = true, .pwm_hz = 25000};
    assert(!db_request_validate(&cpu, error, sizeof(error)));
    assert(strstr(error, "only to FAN_PWM_HOLD"));
    cpu.pwm_hz_set = false;
    cpu.sink_duty_set = true;
    assert(!db_request_validate(&cpu, error, sizeof(error)));
    cpu.sink_duty_set = false;
    assert(db_request_validate(&cpu, error, sizeof(error)));
}

static void test_parameter_bounds(void) {
#if DB_FAN_FIXTURE_BUILD
    char error[96];
    db_run_request_t request = fan_request(DB_FAN_PWM_HZ_MIN, 0, 1);
    assert(db_request_validate(&request, error, sizeof(error)));
    request = fan_request(DB_FAN_PWM_HZ_MAX, 1000, 3600000);
    assert(db_request_validate(&request, error, sizeof(error)));
    request = fan_request(DB_FAN_PWM_HZ_MIN - 1, 500, 1000);
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "pwm_hz"));
    request = fan_request(DB_FAN_PWM_HZ_MAX + 1, 500, 1000);
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "pwm_hz"));
    request = fan_request(25000, 1001, 1000);
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "sink_duty_pct"));
    request = fan_request(25000, 500, 0);
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "duration_ms"));
    request = fan_request(25000, 500, 3600001);
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "duration_ms"));
    request = fan_request(25000, 500, 1000);
    request.pwm_hz_set = false;
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "pwm_hz"));
    request = fan_request(25000, 500, 1000);
    request.sink_duty_set = false;
    assert(!db_request_validate(&request, error, sizeof(error)) && strstr(error, "sink_duty_pct"));
#endif
    uint16_t tenths = 0;
    assert(db_fan_sink_duty_from_pct(0.0, &tenths) && tenths == 0);
    assert(db_fan_sink_duty_from_pct(100.0, &tenths) && tenths == 1000);
    assert(db_fan_sink_duty_from_pct(33.3, &tenths) && tenths == 333);
    assert(db_fan_sink_duty_from_pct(0.1, &tenths) && tenths == 1);
    assert(!db_fan_sink_duty_from_pct(33.35, &tenths));
    assert(!db_fan_sink_duty_from_pct(-0.1, &tenths));
    assert(!db_fan_sink_duty_from_pct(100.1, &tenths));
    assert(!db_fan_sink_duty_from_pct(NAN, &tenths));
    assert(!db_fan_sink_duty_from_pct(INFINITY, &tenths));
}

static void test_pwm_plan(void) {
    db_fan_pwm_plan_t plan;
    assert(db_fan_pwm_plan(25000, 500, &plan));
    assert(plan.resolution_bits == 11 && plan.duty_counts == 1024 && plan.applied_milli_pct == 50000);
    assert(db_fan_pwm_plan(25000, 333, &plan));
    assert(plan.duty_counts == 682 && plan.applied_milli_pct == 33301);
    assert(db_fan_pwm_plan(DB_FAN_PWM_HZ_MIN, 1000, &plan));
    assert(plan.resolution_bits == 14 && plan.duty_counts == 16384 && plan.applied_milli_pct == 100000);
    assert(db_fan_pwm_plan(DB_FAN_PWM_HZ_MAX, 0, &plan));
    assert(plan.resolution_bits == 10 && plan.duty_counts == 0 && plan.applied_milli_pct == 0);
    assert(!db_fan_pwm_plan(DB_FAN_PWM_HZ_MIN - 1, 500, &plan));
    assert(!db_fan_pwm_plan(DB_FAN_PWM_HZ_MAX + 1, 500, &plan));
    assert(!db_fan_pwm_plan(25000, 1001, &plan));
    // Every accepted frequency keeps 0.1 % resolution and a legal LEDC divider,
    // and the programmed duty is within half a count of the request.
    static const uint16_t duties[] = {1, 355, 999};
    for (uint32_t hz = DB_FAN_PWM_HZ_MIN; hz <= DB_FAN_PWM_HZ_MAX; ++hz) {
        for (size_t i = 0; i < sizeof(duties) / sizeof(duties[0]); ++i) {
            assert(db_fan_pwm_plan(hz, duties[i], &plan));
            assert(plan.resolution_bits >= DB_FAN_MIN_RESOLUTION_BITS &&
                   plan.resolution_bits <= DB_FAN_MAX_RESOLUTION_BITS);
            const uint64_t divider_x256 =
                (uint64_t)DB_FAN_LEDC_SOURCE_HZ * 256U / ((uint64_t)hz << plan.resolution_bits);
            assert(divider_x256 >= 256U && divider_x256 <= DB_FAN_LEDC_DIVIDER_MAX_X256);
            const int64_t error_milli = (int64_t)plan.applied_milli_pct - (int64_t)duties[i] * 100;
            const int64_t half_count_milli = (100000 >> plan.resolution_bits) / 2 + 1;
            assert(error_milli <= half_count_milli && error_milli >= -half_count_milli);
        }
    }
}

static void test_tach_math(void) {
    uint64_t milli = 0;
    assert(db_fan_edge_hz_milli(100, 1000000, &milli) && milli == 100000);
    assert(db_fan_edge_hz_milli(1, 3000000, &milli) && milli == 333);
    assert(db_fan_edge_hz_milli(2, 3000000, &milli) && milli == 667);
    assert(db_fan_edge_hz_milli(0, 1000000, &milli) && milli == 0);
    assert(db_fan_edge_hz_milli(600, 1000000, &milli) && milli == 600000);
    assert(!db_fan_edge_hz_milli(10, 0, &milli));
    assert(!db_fan_edge_hz_milli(10, -1, &milli));
    assert(!db_fan_edge_hz_milli(-1, 1000000, &milli));
    // RPM only with a configured PPR.
    assert(!db_fan_rpm_milli(200, 1000000, 0, &milli));
    assert(db_fan_rpm_milli(200, 1000000, 2, &milli) && milli == 6000000);
    assert(db_fan_rpm_milli(300, 1000000, 1, &milli) && milli == 18000000);
    assert(!db_fan_rpm_milli(200, 1000000, DB_FAN_TACH_PPR_MAX + 1, &milli));
    assert(!db_fan_rpm_milli(200, 0, 2, &milli));
}

static void test_metrics_unknown_and_known_ppr(void) {
    db_fan_hold_result_t result = {
        .window_start_us = 1000000, .window_end_us = 3000000, .released_us = 3000100,
        .edge_count = 400, .tach_valid = true, .released = true,
    };
    char metrics[DB_FAN_METRICS_JSON_LEN];
    assert(db_fan_format_metrics(metrics, sizeof(metrics), &result, 0));
    assert(strcmp(metrics, "{\"tach_edges\":400,\"window_start_us\":1000000,\"window_us\":2000000,"
                           "\"edge_hz\":200.000,\"ppr\":null,\"rpm\":null,\"released_us\":3000100}") == 0);
    assert(db_fan_format_metrics(metrics, sizeof(metrics), &result, 2));
    assert(strstr(metrics, "\"ppr\":2,\"rpm\":6000.000"));
    result.tach_valid = false;
    result.released = false;
    result.error = "tach_read_failed";
    assert(db_fan_format_metrics(metrics, sizeof(metrics), &result, 0));
    assert(strcmp(metrics, "{\"released\":false,\"fixture_error\":\"tach_read_failed\"}") == 0);
    assert(!db_fan_format_metrics(metrics, 20, &result, 0));
}

static void assert_released(const fake_fixture_t *fake, const db_fan_hold_result_t *result) {
    assert(fake->line == LINE_RELEASED);
    assert(result->released);
}

static void test_release_on_every_path(void) {
    fake_fixture_t fake;
    db_fan_ops_t ops = fake_ops(&fake);
    db_fan_hold_result_t result;

    // Boot: the default state is released.
    assert(db_fan_boot_release(&ops) && fake.line == LINE_RELEASED && fake.apply_calls == 0);

    // Run end.
    ops = fake_ops(&fake);
    fake.tach_edges_per_ms = 3;
    assert(db_fan_hold(&ops, 25000, 355, 2000, &result) == DB_FAN_HOLD_PASS);
    assert_released(&fake, &result);
    assert(fake.release_calls == 2 && fake.apply_calls == 1 && fake.applied_hz == 25000);
    assert(fake.applied_plan.duty_counts == result.plan.duty_counts);
    assert(result.tach_valid && !result.error);
    assert(result.window_end_us - result.window_start_us == 2000000);
    assert(result.edge_count == 6000 && result.released_us >= result.window_end_us);

    // Abort.
    ops = fake_ops(&fake);
    fake.abort_after_polls = 5;
    assert(db_fan_hold(&ops, 25000, 500, 60000, &result) == DB_FAN_HOLD_ABORTED);
    assert_released(&fake, &result);
    assert(result.tach_valid && !result.error);
    assert(result.window_end_us - result.window_start_us == 5 * DB_FAN_ABORT_POLL_MS * 1000);

    // Errors: apply, tach clear, tach read.
    ops = fake_ops(&fake);
    fake.fail_apply = true;
    assert(db_fan_hold(&ops, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert_released(&fake, &result);
    assert(strcmp(result.error, "apply_failed") == 0);

    ops = fake_ops(&fake);
    fake.fail_tach_clear = true;
    assert(db_fan_hold(&ops, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert_released(&fake, &result);
    assert(strcmp(result.error, "tach_clear_failed") == 0 && !result.tach_valid);

    ops = fake_ops(&fake);
    fake.fail_tach_read = true;
    assert(db_fan_hold(&ops, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert_released(&fake, &result);
    assert(strcmp(result.error, "tach_read_failed") == 0 && !result.tach_valid);

    // Invalid parameters never reach apply and still release.
    ops = fake_ops(&fake);
    assert(db_fan_hold(&ops, 5, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert_released(&fake, &result);
    assert(fake.apply_calls == 0 && strcmp(result.error, "invalid_parameters") == 0);
    ops = fake_ops(&fake);
    assert(db_fan_hold(&ops, 25000, 500, 0, &result) == DB_FAN_HOLD_FAIL);
    assert(fake.apply_calls == 0);

    // A stimulus is never applied unless the line was first released.
    ops = fake_ops(&fake);
    fake.failing_release_call = 1;
    assert(db_fan_hold(&ops, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(fake.apply_calls == 0 && strcmp(result.error, "pre_release_failed") == 0);
    assert_released(&fake, &result); // the exit-path release still ran

    // A release that cannot be verified is a failure even after a clean hold.
    ops = fake_ops(&fake);
    fake.failing_release_call = 2;
    assert(db_fan_hold(&ops, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(!result.released && strcmp(result.error, "release_failed") == 0);
    assert(fake.line == LINE_DRIVEN);

    assert(db_fan_hold(NULL, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(!db_fan_boot_release(NULL));
}

// The phase_end envelope must fit one event slot; main.c stores truncated JSON
// otherwise. Uses generous but physically plausible values: ~115 days uptime,
// a one-hour hold at 30 kHz edges, PPR 1, and a failed release.
static void test_phase_end_fits_event_slot(void) {
    db_fan_pwm_plan_t plan;
    assert(db_fan_pwm_plan(DB_FAN_PWM_HZ_MAX, 999, &plan));
    char parameters[DB_FAN_PARAMETERS_JSON_LEN];
    assert(db_fan_format_parameters(parameters, sizeof(parameters), DB_FAN_PWM_HZ_MAX, 999, 3600000, &plan));
    db_fan_hold_result_t result = {
        .window_start_us = 9999999999999LL, .window_end_us = 9999999999999LL + 3600000000LL,
        .released_us = 9999999999999LL + 3600001000LL, .edge_count = 108000000, .tach_valid = true,
        .released = false, .error = "release_failed",
    };
    char metrics[DB_FAN_METRICS_JSON_LEN];
    assert(db_fan_format_metrics(metrics, sizeof(metrics), &result, 1));
    char envelope[1024];
    const int length = snprintf(envelope, sizeof(envelope),
                                "{\"schema\":1,\"event\":\"phase_end\",\"seq\":99999999,\"uptime_ms\":9999999999,"
                                "\"target\":\"esp32s3-tinys3d\",\"firmware_version\":\"0.1.0\",\"phase\":\"FAN_PWM_HOLD\","
                                "\"run_id\":\"ffffffff-ffffffff\",\"result\":\"aborted\",\"parameters\":%s,\"metrics\":%s}",
                                parameters, metrics);
    assert(length > 0 && length < DB_EVENT_JSON_LEN);
}

int main(void) {
    test_capability_gate();
    test_parameter_bounds();
    test_pwm_plan();
    test_tach_math();
    test_metrics_unknown_and_known_ppr();
    test_release_on_every_path();
    test_phase_end_fits_event_slot();
    printf("db_fan tests passed (%s profile)\n", DB_FAN_FIXTURE_BUILD ? "fan-fixture" : "normal");
    return 0;
}
