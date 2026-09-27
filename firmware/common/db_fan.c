#include "db_fan.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

bool db_fan_pwm_hz_valid(uint32_t pwm_hz) {
    return pwm_hz >= DB_FAN_PWM_HZ_MIN && pwm_hz <= DB_FAN_PWM_HZ_MAX;
}

bool db_fan_sink_duty_valid(uint16_t sink_duty_tenths_pct) {
    return sink_duty_tenths_pct <= DB_FAN_SINK_DUTY_TENTHS_MAX;
}

bool db_fan_sink_duty_from_pct(double sink_duty_pct, uint16_t *tenths_out) {
    // Written so NaN fails both comparisons.
    if (!tenths_out || !(sink_duty_pct >= 0.0 && sink_duty_pct <= 100.0)) return false;
    const double scaled = sink_duty_pct * 10.0;
    const long tenths = (long)(scaled + 0.5);
    const double residue = scaled - (double)tenths;
    if (residue > 1e-6 || residue < -1e-6) return false;
    *tenths_out = (uint16_t)tenths;
    return true;
}

bool db_fan_pwm_plan(uint32_t pwm_hz, uint16_t sink_duty_tenths_pct, db_fan_pwm_plan_t *plan) {
    if (!plan || !db_fan_pwm_hz_valid(pwm_hz) || !db_fan_sink_duty_valid(sink_duty_tenths_pct)) return false;
    uint32_t bits = DB_FAN_MAX_RESOLUTION_BITS;
    while (bits > 0 && (uint64_t)pwm_hz << bits > DB_FAN_LEDC_SOURCE_HZ) --bits;
    if (bits < DB_FAN_MIN_RESOLUTION_BITS) return false;
    const uint64_t divider_x256 = ((uint64_t)DB_FAN_LEDC_SOURCE_HZ * 256U) / ((uint64_t)pwm_hz << bits);
    if (divider_x256 < 256U || divider_x256 > DB_FAN_LEDC_DIVIDER_MAX_X256) return false;
    const uint64_t full_scale = 1ULL << bits;
    plan->resolution_bits = bits;
    plan->duty_counts = (uint32_t)((sink_duty_tenths_pct * full_scale + DB_FAN_SINK_DUTY_TENTHS_MAX / 2U) /
                                   DB_FAN_SINK_DUTY_TENTHS_MAX);
    plan->applied_milli_pct = (uint32_t)((plan->duty_counts * 100000ULL + full_scale / 2U) / full_scale);
    return true;
}

bool db_fan_edge_hz_milli(int64_t edge_count, int64_t window_us, uint64_t *hz_milli) {
    if (!hz_milli || window_us <= 0 || edge_count < 0 || edge_count > INT64_MAX / 1000000000LL) return false;
    *hz_milli = (uint64_t)((edge_count * 1000000000LL + window_us / 2) / window_us);
    return true;
}

bool db_fan_rpm_milli(int64_t edge_count, int64_t window_us, uint32_t ppr, uint64_t *rpm_milli) {
    if (!rpm_milli || ppr == 0 || ppr > DB_FAN_TACH_PPR_MAX || window_us <= 0 || edge_count < 0 ||
        edge_count > INT64_MAX / 60000000000LL || window_us > INT64_MAX / (int64_t)ppr)
        return false;
    const int64_t denominator = window_us * (int64_t)ppr;
    *rpm_milli = (uint64_t)((edge_count * 60000000000LL + denominator / 2) / denominator);
    return true;
}

bool db_fan_boot_release(const db_fan_ops_t *ops) {
    return ops && ops->release && ops->release(ops->ctx);
}

db_fan_hold_outcome_t db_fan_hold(const db_fan_ops_t *ops, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                                  uint32_t duration_ms, db_fan_hold_result_t *result) {
    if (!result) return DB_FAN_HOLD_FAIL;
    memset(result, 0, sizeof(*result));
    if (!ops) {
        result->error = "no_fixture";
        return DB_FAN_HOLD_FAIL;
    }
    db_fan_hold_outcome_t outcome = DB_FAN_HOLD_PASS;
    if (duration_ms == 0 || !db_fan_pwm_plan(pwm_hz, sink_duty_tenths_pct, &result->plan)) {
        result->error = "invalid_parameters";
        outcome = DB_FAN_HOLD_FAIL;
        goto release;
    }
    // Start from a known released line even if a previous exit path misbehaved.
    if (!ops->release(ops->ctx)) {
        result->error = "pre_release_failed";
        outcome = DB_FAN_HOLD_FAIL;
        goto release;
    }
    if (!ops->apply(ops->ctx, pwm_hz, &result->plan)) {
        result->error = "apply_failed";
        outcome = DB_FAN_HOLD_FAIL;
        goto release;
    }
    if (!ops->tach_clear(ops->ctx)) {
        result->error = "tach_clear_failed";
        outcome = DB_FAN_HOLD_FAIL;
        goto release;
    }
    result->window_start_us = ops->now_us(ops->ctx);
    const int64_t deadline_us = result->window_start_us + (int64_t)duration_ms * 1000;
    for (;;) {
        const int64_t now_us = ops->now_us(ops->ctx);
        if (now_us >= deadline_us) break;
        if (ops->should_abort(ops->ctx)) {
            outcome = DB_FAN_HOLD_ABORTED;
            break;
        }
        const int64_t remaining_ms = (deadline_us - now_us + 999) / 1000;
        ops->sleep_ms(ops->ctx, remaining_ms < DB_FAN_ABORT_POLL_MS ? (uint32_t)remaining_ms : DB_FAN_ABORT_POLL_MS);
    }
    if (ops->tach_read(ops->ctx, &result->edge_count)) {
        result->tach_valid = true;
    } else {
        result->edge_count = 0;
        result->error = "tach_read_failed";
        outcome = DB_FAN_HOLD_FAIL;
    }
    result->window_end_us = ops->now_us(ops->ctx);

release:
    result->released = ops->release && ops->release(ops->ctx);
    result->released_us = ops->now_us ? ops->now_us(ops->ctx) : 0;
    if (!result->released) {
        if (!result->error) result->error = "release_failed";
        outcome = DB_FAN_HOLD_FAIL;
    }
    return outcome;
}

__attribute__((format(printf, 4, 5)))
static bool append(char *out, size_t out_len, size_t *used, const char *format, ...) {
    va_list args;
    va_start(args, format);
    const int written = vsnprintf(out + *used, out_len - *used, format, args);
    va_end(args);
    if (written < 0 || (size_t)written >= out_len - *used) return false;
    *used += (size_t)written;
    return true;
}

bool db_fan_format_parameters(char *out, size_t out_len, uint32_t pwm_hz, uint16_t sink_duty_tenths_pct,
                              uint32_t duration_ms, const db_fan_pwm_plan_t *plan) {
    if (!out || out_len == 0) return false;
    int written;
    if (plan && plan->resolution_bits) {
        written = snprintf(out, out_len,
                           "{\"pwm_hz\":%" PRIu32 ",\"sink_duty_pct\":%u.%u,\"duration_ms\":%" PRIu32
                           ",\"applied_sink_duty_pct\":%" PRIu32 ".%03" PRIu32 ",\"duty_resolution_bits\":%" PRIu32 "}",
                           pwm_hz, sink_duty_tenths_pct / 10U, sink_duty_tenths_pct % 10U, duration_ms,
                           plan->applied_milli_pct / 1000U, plan->applied_milli_pct % 1000U, plan->resolution_bits);
    } else {
        written = snprintf(out, out_len, "{\"pwm_hz\":%" PRIu32 ",\"sink_duty_pct\":%u.%u,\"duration_ms\":%" PRIu32 "}",
                           pwm_hz, sink_duty_tenths_pct / 10U, sink_duty_tenths_pct % 10U, duration_ms);
    }
    return written > 0 && (size_t)written < out_len;
}

bool db_fan_format_metrics(char *out, size_t out_len, const db_fan_hold_result_t *result, uint32_t ppr) {
    if (!out || out_len == 0 || !result) return false;
    size_t used = 0;
    bool ok = append(out, out_len, &used, "{");
    if (result->tach_valid) {
        const int64_t window_us = result->window_end_us - result->window_start_us;
        uint64_t hz_milli = 0, rpm_milli = 0;
        ok = ok && append(out, out_len, &used, "\"tach_edges\":%" PRId64 ",\"window_start_us\":%" PRId64
                          ",\"window_us\":%" PRId64, result->edge_count, result->window_start_us, window_us);
        if (db_fan_edge_hz_milli(result->edge_count, window_us, &hz_milli))
            ok = ok && append(out, out_len, &used, ",\"edge_hz\":%" PRIu64 ".%03" PRIu64, hz_milli / 1000U,
                              hz_milli % 1000U);
        else
            ok = ok && append(out, out_len, &used, ",\"edge_hz\":null");
        // Unknown PPR (0) stays an explicit null and RPM is never derived.
        if (ppr != 0 && db_fan_rpm_milli(result->edge_count, window_us, ppr, &rpm_milli))
            ok = ok && append(out, out_len, &used, ",\"ppr\":%" PRIu32 ",\"rpm\":%" PRIu64 ".%03" PRIu64, ppr,
                              rpm_milli / 1000U, rpm_milli % 1000U);
        else
            ok = ok && append(out, out_len, &used, ",\"ppr\":%s,\"rpm\":null", ppr ? "\"invalid\"" : "null");
        ok = ok && append(out, out_len, &used, ",");
    }
    if (result->released)
        ok = ok && append(out, out_len, &used, "\"released_us\":%" PRId64, result->released_us);
    else
        ok = ok && append(out, out_len, &used, "\"released\":false");
    if (result->error) ok = ok && append(out, out_len, &used, ",\"fixture_error\":\"%s\"", result->error);
    return ok && append(out, out_len, &used, "}");
}
