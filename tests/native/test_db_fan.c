// Fan-characterization common logic. Built twice: as the baseline experiment
// profile, and with -DCONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION=1.

#include "db_fan.h"
#include "db_run.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

// Models the gate pad and the external stage: which level the pad sits at
// (static) or which PWM it carries, and every hardware call in order.
typedef struct {
    int gate_sink_level;
    int pad_level; // -1: never driven
    bool pwm_active;
    uint32_t pwm_hz, pwm_bits, pwm_counts;
    bool pwm_invert;
    int64_t clock_us;
    int drive_calls;
    int failing_drive_call; // 0: never
    int abort_after_polls;  // <0: never
    int polls;
    bool tach_available;
    bool fail_pwm;
    bool fail_tach_clear;
    bool fail_tach_read;
    int64_t tach_edges_per_ms;
    int64_t tach_origin_us;
    char log[256];
} fake_fixture_t;

static void note(fake_fixture_t *fake, const char *entry) {
    strncat(fake->log, entry, sizeof(fake->log) - strlen(fake->log) - 1);
}

static bool fake_drive_static(void *ctx, int gate_level) {
    fake_fixture_t *fake = ctx;
    ++fake->drive_calls;
    note(fake, gate_level ? "S1 " : "S0 ");
    if (fake->failing_drive_call == fake->drive_calls) return false;
    fake->pwm_active = false;
    fake->pad_level = gate_level;
    return true;
}

static bool fake_start_pwm(void *ctx, uint32_t pwm_hz, uint32_t bits, uint32_t counts, bool invert) {
    fake_fixture_t *fake = ctx;
    note(fake, "PWM ");
    // Mirrors the ESP32-S3 LEDC constraint the planner must respect.
    assert(counts > 0 && counts < (1U << bits));
    fake->pwm_active = true; // a failed configuration may already drive the pad
    if (fake->fail_pwm) return false;
    fake->pwm_hz = pwm_hz;
    fake->pwm_bits = bits;
    fake->pwm_counts = counts;
    fake->pwm_invert = invert;
    return true;
}

static bool fake_tach_ready(void *ctx) {
    fake_fixture_t *fake = ctx;
    note(fake, "READY ");
    return fake->tach_available;
}

static bool fake_tach_clear(void *ctx) {
    fake_fixture_t *fake = ctx;
    note(fake, "CLEAR ");
    fake->tach_origin_us = fake->clock_us;
    return !fake->fail_tach_clear;
}

static bool fake_tach_read(void *ctx, int64_t *edges) {
    fake_fixture_t *fake = ctx;
    note(fake, "READ ");
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

static const db_fan_ops_t fake_ops_table = {fake_drive_static, fake_start_pwm, fake_tach_ready, fake_tach_clear,
                                            fake_tach_read,    fake_now,       fake_should_abort, fake_sleep, NULL};

typedef struct {
    fake_fixture_t fake;
    db_fan_ops_t ops;
    db_fan_fixture_t fixture;
} fake_bench_t;

static void fake_bench(fake_bench_t *bench, int gate_sink_level) {
    memset(bench, 0, sizeof(*bench));
    bench->fake.gate_sink_level = gate_sink_level;
    bench->fake.pad_level = -1;
    bench->fake.abort_after_polls = -1;
    bench->fake.clock_us = 5000000;
    bench->fake.tach_available = true;
    bench->ops = fake_ops_table;
    bench->ops.ctx = &bench->fake;
    bench->fixture.ops = &bench->ops;
    bench->fixture.gate_sink_level = gate_sink_level;
}

// Fraction of time, in milli-percent, the modeled stage sinks the fan line.
static uint32_t line_sink_milli_pct(const fake_fixture_t *fake) {
    if (!fake->pwm_active) return fake->pad_level == fake->gate_sink_level ? 100000U : 0U;
    const uint64_t full = 1ULL << fake->pwm_bits;
    const uint64_t pad_high = fake->pwm_invert ? full - fake->pwm_counts : fake->pwm_counts;
    const uint64_t sinking = fake->gate_sink_level ? pad_high : full - pad_high;
    return (uint32_t)((sinking * 100000U + full / 2U) / full);
}

static bool line_released(const fake_fixture_t *fake) {
    return !fake->pwm_active && fake->pad_level == (fake->gate_sink_level ? 0 : 1);
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
    assert(db_workload_supported(DB_FAN_PWM_HOLD) == (DB_EXPERIMENT_FAN_CHARACTERIZATION == 1));
    db_run_request_t request = fan_request(25000, 500, 1000);
#if DB_EXPERIMENT_FAN_CHARACTERIZATION
    assert(db_request_validate(&request, error, sizeof(error)));
#else
    assert(!db_request_validate(&request, error, sizeof(error)));
    assert(strcmp(error, "FAN_PWM_HOLD requires the fan-characterization experiment profile") == 0);
    // Every other workload stays available in the baseline profile.
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
#if DB_EXPERIMENT_FAN_CHARACTERIZATION
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

static void test_stimulus_plan(void) {
    db_fan_stimulus_t stimulus;
    // 0 % and 100 % are static gate levels, never LEDC.
    assert(db_fan_stimulus_plan(25000, 0, &stimulus));
    assert(stimulus.mode == DB_FAN_STIMULUS_STATIC_RELEASE && stimulus.resolution_bits == 0 &&
           stimulus.duty_counts == 0 && stimulus.applied_milli_pct == 0);
    assert(db_fan_stimulus_plan(DB_FAN_PWM_HZ_MIN, 1000, &stimulus));
    assert(stimulus.mode == DB_FAN_STIMULUS_STATIC_SINK && stimulus.resolution_bits == 0 &&
           stimulus.duty_counts == 0 && stimulus.applied_milli_pct == 100000);
    assert(strcmp(db_fan_stimulus_mode_name(DB_FAN_STIMULUS_STATIC_SINK), "static_sink") == 0);
    assert(db_fan_stimulus_plan(25000, 500, &stimulus));
    assert(stimulus.mode == DB_FAN_STIMULUS_PWM && stimulus.resolution_bits == 11 && stimulus.duty_counts == 1024 &&
           stimulus.applied_milli_pct == 50000);
    assert(db_fan_stimulus_plan(25000, 333, &stimulus));
    assert(stimulus.duty_counts == 682 && stimulus.applied_milli_pct == 33301);
    assert(!db_fan_stimulus_plan(DB_FAN_PWM_HZ_MIN - 1, 500, &stimulus));
    assert(!db_fan_stimulus_plan(DB_FAN_PWM_HZ_MAX + 1, 500, &stimulus));
    assert(!db_fan_stimulus_plan(25000, 1001, &stimulus));
    // Every accepted frequency keeps 0.1 % resolution and a legal LEDC divider,
    // the compare value stays strictly inside 1..2^bits-1, and the programmed
    // duty is within half a count of the request.
    static const uint16_t duties[] = {1, 355, 999};
    for (uint32_t hz = DB_FAN_PWM_HZ_MIN; hz <= DB_FAN_PWM_HZ_MAX; ++hz) {
        for (size_t i = 0; i < sizeof(duties) / sizeof(duties[0]); ++i) {
            assert(db_fan_stimulus_plan(hz, duties[i], &stimulus));
            assert(stimulus.mode == DB_FAN_STIMULUS_PWM);
            assert(stimulus.resolution_bits >= DB_FAN_MIN_RESOLUTION_BITS &&
                   stimulus.resolution_bits <= DB_FAN_MAX_RESOLUTION_BITS);
            const uint64_t divider_x256 =
                (uint64_t)DB_FAN_LEDC_SOURCE_HZ * 256U / ((uint64_t)hz << stimulus.resolution_bits);
            assert(divider_x256 >= 256U && divider_x256 <= DB_FAN_LEDC_DIVIDER_MAX_X256);
            assert(stimulus.duty_counts >= 1 && stimulus.duty_counts < (1U << stimulus.resolution_bits));
            const int64_t error_milli = (int64_t)stimulus.applied_milli_pct - (int64_t)duties[i] * 100;
            const int64_t half_count_milli = (100000 >> stimulus.resolution_bits) / 2 + 1;
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

static void test_parameters_name_the_stimulus(void) {
    char parameters[DB_FAN_PARAMETERS_JSON_LEN];
    db_fan_stimulus_t stimulus;
    assert(db_fan_stimulus_plan(25000, 0, &stimulus));
    assert(db_fan_format_parameters(parameters, sizeof(parameters), 25000, 0, 1000, &stimulus));
    assert(strcmp(parameters, "{\"pwm_hz\":25000,\"sink_duty_pct\":0.0,\"duration_ms\":1000,"
                              "\"stimulus\":\"static_release\",\"applied_sink_duty_pct\":0.000}") == 0);
    assert(db_fan_stimulus_plan(25000, 1000, &stimulus));
    assert(db_fan_format_parameters(parameters, sizeof(parameters), 25000, 1000, 1000, &stimulus));
    assert(strcmp(parameters, "{\"pwm_hz\":25000,\"sink_duty_pct\":100.0,\"duration_ms\":1000,"
                              "\"stimulus\":\"static_sink\",\"applied_sink_duty_pct\":100.000}") == 0);
    assert(db_fan_stimulus_plan(25000, 355, &stimulus));
    assert(db_fan_format_parameters(parameters, sizeof(parameters), 25000, 355, 1000, &stimulus));
    assert(strstr(parameters, "\"stimulus\":\"pwm\",\"applied_sink_duty_pct\":35.498,\"duty_resolution_bits\":11}"));
}

// 0 %, an intermediate PWM value, and 100 % for one stage polarity: the
// endpoints never touch PWM, and the line ends released even when aborted.
static void test_stimulus_modes_for_polarity(int gate_sink_level) {
    static const struct {
        uint16_t tenths;
        db_fan_stimulus_mode_t mode;
        bool uses_pwm;
    } cases[] = {
        {0, DB_FAN_STIMULUS_STATIC_RELEASE, false},
        {355, DB_FAN_STIMULUS_PWM, true},
        {1000, DB_FAN_STIMULUS_STATIC_SINK, false},
    };
    const int release_level = gate_sink_level ? 0 : 1;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        fake_bench_t bench;
        fake_bench(&bench, gate_sink_level);
        assert(db_fan_release_level(&bench.fixture) == release_level);
        bench.fake.abort_after_polls = 3;
        db_fan_hold_result_t result;
        assert(db_fan_hold(&bench.fixture, 25000, cases[i].tenths, 60000, &result) == DB_FAN_HOLD_ABORTED);
        assert(result.stimulus.mode == cases[i].mode);
        assert(result.actuated == (cases[i].mode != DB_FAN_STIMULUS_STATIC_RELEASE));
        assert(line_released(&bench.fake) && result.released);
        assert((strstr(bench.fake.log, "PWM") != NULL) == cases[i].uses_pwm);
    }
}

// Captures the modeled line state while the hold is running.
static uint32_t observed_sink_milli_pct;
static bool observing_should_abort(void *ctx) {
    observed_sink_milli_pct = line_sink_milli_pct(ctx);
    return false;
}

static void test_hold_drives_requested_sink_fraction(int gate_sink_level) {
    static const uint16_t duties[] = {0, 1, 355, 999, 1000};
    for (size_t i = 0; i < sizeof(duties) / sizeof(duties[0]); ++i) {
        fake_bench_t bench;
        fake_bench(&bench, gate_sink_level);
        bench.ops.should_abort = observing_should_abort;
        observed_sink_milli_pct = UINT32_MAX;
        db_fan_hold_result_t result;
        assert(db_fan_hold(&bench.fixture, 25000, duties[i], 100, &result) == DB_FAN_HOLD_PASS);
        assert(observed_sink_milli_pct == result.stimulus.applied_milli_pct);
        assert(line_released(&bench.fake) && result.released);
    }
}

static void test_release_on_every_path(void) {
    fake_bench_t bench;
    db_fan_hold_result_t result;

    // Boot: the default state is released, and nothing else is touched.
    fake_bench(&bench, 1);
    assert(db_fan_release(&bench.fixture) && line_released(&bench.fake));
    assert(strcmp(bench.fake.log, "S0 ") == 0);
    fake_bench(&bench, 0);
    assert(db_fan_release(&bench.fixture) && line_released(&bench.fake));
    assert(strcmp(bench.fake.log, "S1 ") == 0);

    // Run end: release, tach readiness, actuate, clear, hold, read, release.
    fake_bench(&bench, 1);
    bench.fake.tach_edges_per_ms = 3;
    assert(db_fan_hold(&bench.fixture, 25000, 355, 2000, &result) == DB_FAN_HOLD_PASS);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(bench.fake.log, "S0 READY PWM CLEAR READ S0 ") == 0);
    assert(bench.fake.pwm_hz == 25000 && bench.fake.pwm_counts == result.stimulus.duty_counts);
    assert(result.tach_valid && !result.error);
    assert(result.window_end_us - result.window_start_us == 2000000);
    assert(result.edge_count == 6000 && result.released_us >= result.window_end_us);

    // Abort.
    fake_bench(&bench, 1);
    bench.fake.abort_after_polls = 5;
    assert(db_fan_hold(&bench.fixture, 25000, 1000, 60000, &result) == DB_FAN_HOLD_ABORTED);
    assert(line_released(&bench.fake) && result.released);
    assert(result.tach_valid && !result.error);
    assert(result.window_end_us - result.window_start_us == 5 * DB_FAN_ABORT_POLL_MS * 1000);
    assert(strcmp(bench.fake.log, "S0 READY S1 CLEAR READ S0 ") == 0);

    // Tach unavailable: refused before any actuation.
    for (int level = 0; level <= 1; ++level) {
        static const uint16_t duties[] = {0, 355, 1000};
        for (size_t i = 0; i < sizeof(duties) / sizeof(duties[0]); ++i) {
            fake_bench(&bench, level);
            bench.fake.tach_available = false;
            assert(db_fan_hold(&bench.fixture, 25000, duties[i], 1000, &result) == DB_FAN_HOLD_FAIL);
            assert(strcmp(result.error, "tach_unavailable") == 0 && !result.actuated && !result.tach_valid);
            assert(strcmp(bench.fake.log, level ? "S0 READY S0 " : "S1 READY S1 ") == 0);
            assert(line_released(&bench.fake) && result.released);
        }
    }

    // Errors after readiness: PWM, static sink, tach clear, tach read.
    fake_bench(&bench, 1);
    bench.fake.fail_pwm = true;
    assert(db_fan_hold(&bench.fixture, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(result.error, "actuation_failed") == 0);

    fake_bench(&bench, 0);
    bench.fake.failing_drive_call = 2; // the static-sink drive
    assert(db_fan_hold(&bench.fixture, 25000, 1000, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(result.error, "actuation_failed") == 0);

    fake_bench(&bench, 1);
    bench.fake.fail_tach_clear = true;
    assert(db_fan_hold(&bench.fixture, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(result.error, "tach_clear_failed") == 0 && !result.tach_valid);

    fake_bench(&bench, 1);
    bench.fake.fail_tach_read = true;
    assert(db_fan_hold(&bench.fixture, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(result.error, "tach_read_failed") == 0 && !result.tach_valid);

    // Invalid parameters never reach actuation and still release.
    fake_bench(&bench, 1);
    assert(db_fan_hold(&bench.fixture, 5, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(line_released(&bench.fake) && result.released);
    assert(strcmp(bench.fake.log, "S0 ") == 0 && strcmp(result.error, "invalid_parameters") == 0);
    fake_bench(&bench, 1);
    assert(db_fan_hold(&bench.fixture, 25000, 500, 0, &result) == DB_FAN_HOLD_FAIL);
    assert(strcmp(bench.fake.log, "S0 ") == 0);

    // Nothing is actuated unless the line was first released.
    fake_bench(&bench, 1);
    bench.fake.failing_drive_call = 1;
    assert(db_fan_hold(&bench.fixture, 25000, 1000, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(strcmp(result.error, "pre_release_failed") == 0);
    assert(strcmp(bench.fake.log, "S0 S0 ") == 0); // the exit-path release still ran
    assert(line_released(&bench.fake) && result.released);

    // A release that cannot be verified is a failure even after a clean hold.
    fake_bench(&bench, 1);
    bench.fake.failing_drive_call = 3; // pre-release, static sink, final release
    assert(db_fan_hold(&bench.fixture, 25000, 1000, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(!result.released && strcmp(result.error, "release_failed") == 0);
    assert(!line_released(&bench.fake));

    // Missing or malformed fixture.
    assert(db_fan_hold(NULL, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(!db_fan_release(NULL));
    fake_bench(&bench, 1);
    bench.fixture.gate_sink_level = 2;
    assert(db_fan_hold(&bench.fixture, 25000, 500, 1000, &result) == DB_FAN_HOLD_FAIL);
    assert(strcmp(bench.fake.log, "") == 0);
}

// The phase_end envelope must fit one event slot; main.c stores truncated JSON
// otherwise. Uses generous but physically plausible values: ~115 days uptime,
// a one-hour hold at 30 kHz edges, PPR 1, and a failed release.
static void test_phase_end_fits_event_slot(void) {
    db_fan_stimulus_t stimulus;
    assert(db_fan_stimulus_plan(DB_FAN_PWM_HZ_MAX, 999, &stimulus));
    char parameters[DB_FAN_PARAMETERS_JSON_LEN];
    assert(db_fan_format_parameters(parameters, sizeof(parameters), DB_FAN_PWM_HZ_MAX, 999, 3600000, &stimulus));
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
    test_stimulus_plan();
    test_tach_math();
    test_metrics_unknown_and_known_ppr();
    test_parameters_name_the_stimulus();
    for (int level = 0; level <= 1; ++level) {
        test_stimulus_modes_for_polarity(level);
        test_hold_drives_requested_sink_fraction(level);
    }
    test_release_on_every_path();
    test_phase_end_fits_event_slot();
    printf("db_fan tests passed (%s experiment profile)\n", DB_EXPERIMENT_PROFILE_NAME);
    return 0;
}
