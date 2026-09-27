#include "fan_fixture.h"

#if DB_FAN_FIXTURE_BUILD

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/pulse_cnt.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// The fixture wiring is bench hardware DragonBench cannot know. Nothing has a
// usable default: an unconfigured fixture build fails here instead of guessing.
#if CONFIG_DB_FAN_PWM_GATE_GPIO < 0
#error "Fan fixture: set CONFIG_DB_FAN_PWM_GATE_GPIO to the GPIO wired to the external open-drain stage gate (docs/FAN_FIXTURE.md)"
#endif
#if CONFIG_DB_FAN_GATE_SINK_LEVEL < 0
#error "Fan fixture: set CONFIG_DB_FAN_GATE_SINK_LEVEL to the gate level (0 or 1) at which the external stage sinks the fan PWM line (docs/FAN_FIXTURE.md)"
#endif
#if CONFIG_DB_FAN_TACH_GPIO < 0
#error "Fan fixture: set CONFIG_DB_FAN_TACH_GPIO to the GPIO wired to the conditioned tach signal (docs/FAN_FIXTURE.md)"
#endif
#if CONFIG_DB_FAN_PWM_GATE_GPIO >= 0 && CONFIG_DB_FAN_GATE_SINK_LEVEL >= 0 && CONFIG_DB_FAN_TACH_GPIO >= 0

#if defined(CONFIG_SPIRAM_MODE_OCT)
#define FAN_OCTAL_PSRAM 1
#else
#define FAN_OCTAL_PSRAM 0
#endif
#if DB_FAN_PIN_RESERVED(CONFIG_DB_FAN_PWM_GATE_GPIO, FAN_OCTAL_PSRAM)
#error "Fan fixture: CONFIG_DB_FAN_PWM_GATE_GPIO is a strapping, USB, flash/PSRAM, console, or nonexistent pin"
#endif
#if DB_FAN_PIN_RESERVED(CONFIG_DB_FAN_TACH_GPIO, FAN_OCTAL_PSRAM)
#error "Fan fixture: CONFIG_DB_FAN_TACH_GPIO is a strapping, USB, flash/PSRAM, console, or nonexistent pin"
#endif
#if CONFIG_DB_FAN_PWM_GATE_GPIO == CONFIG_DB_FAN_TACH_GPIO
#error "Fan fixture: gate and tach must be different GPIOs"
#endif
#if CONFIG_DB_FAN_PWM_GATE_GPIO == CONFIG_DB_RF_SWITCH_GPIO || CONFIG_DB_FAN_TACH_GPIO == CONFIG_DB_RF_SWITCH_GPIO
#error "Fan fixture: GPIO collides with CONFIG_DB_RF_SWITCH_GPIO"
#endif
// RPM is derived only from a PPR that names the evidence that established it.
_Static_assert(CONFIG_DB_FAN_TACH_PPR == 0 || sizeof(CONFIG_DB_FAN_TACH_PPR_EVIDENCE) > 1,
               "Fan fixture: CONFIG_DB_FAN_TACH_PPR needs CONFIG_DB_FAN_TACH_PPR_EVIDENCE");

#if defined(CONFIG_DB_FAN_TACH_INTERNAL_PULLUP)
#define TACH_INTERNAL_PULLUP 1
#else
#define TACH_INTERNAL_PULLUP 0
#endif

#define TAG "fan_fixture"
#define GATE_GPIO ((gpio_num_t)CONFIG_DB_FAN_PWM_GATE_GPIO)
#define TACH_GPIO ((gpio_num_t)CONFIG_DB_FAN_TACH_GPIO)
#define GATE_SINK_LEVEL CONFIG_DB_FAN_GATE_SINK_LEVEL
#define GATE_RELEASE_LEVEL (GATE_SINK_LEVEL ? 0 : 1)
#define FAN_LEDC_MODE LEDC_LOW_SPEED_MODE
#define FAN_LEDC_TIMER LEDC_TIMER_0
#define FAN_LEDC_CHANNEL LEDC_CHANNEL_0
#define TACH_HIGH_LIMIT 32767

typedef enum { LINE_UNCONFIGURED, LINE_RELEASED, LINE_DRIVEN, LINE_RELEASE_FAILED } line_state_t;

static volatile line_state_t line_state = LINE_UNCONFIGURED;
static bool ledc_channel_active;
static pcnt_unit_handle_t tach_unit;
static bool tach_ready;
static bool (*abort_requested)(void);

static const char *line_state_name(line_state_t state) {
    switch (state) {
        case LINE_RELEASED: return "released";
        case LINE_DRIVEN: return "driven";
        case LINE_RELEASE_FAILED: return "release_failed";
        default: return "unconfigured";
    }
}

// Detaches the gate from LEDC by routing it back to a plain GPIO output at the
// release level (output register first, so the switch cannot glitch to sink),
// then reads the pad back. No internal pulls: the external gate resistor owns
// the level whenever the pin is not driven, including reset and boot.
static bool release_line(void *ctx) {
    (void)ctx;
    gpio_set_level(GATE_GPIO, GATE_RELEASE_LEVEL);
    const gpio_config_t gate = {
        .pin_bit_mask = 1ULL << CONFIG_DB_FAN_PWM_GATE_GPIO,
        .mode = GPIO_MODE_INPUT_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    bool ok = gpio_config(&gate) == ESP_OK && gpio_set_level(GATE_GPIO, GATE_RELEASE_LEVEL) == ESP_OK &&
              gpio_get_level(GATE_GPIO) == GATE_RELEASE_LEVEL;
    if (ledc_channel_active) {
        // The pad is already off LEDC; this only stops the channel.
        ledc_stop(FAN_LEDC_MODE, FAN_LEDC_CHANNEL, 0);
        ledc_channel_active = false;
    }
    line_state = ok ? LINE_RELEASED : LINE_RELEASE_FAILED;
    return ok;
}

// LEDC duty is the fraction of each period the stage sinks the line. An
// inverting stage (sink at gate low) inverts the pad instead of the duty.
static bool apply_stimulus(void *ctx, uint32_t pwm_hz, const db_fan_pwm_plan_t *plan) {
    (void)ctx;
    const ledc_timer_config_t timer = {
        .speed_mode = FAN_LEDC_MODE,
        .duty_resolution = (ledc_timer_bit_t)plan->resolution_bits,
        .timer_num = FAN_LEDC_TIMER,
        .freq_hz = pwm_hz,
        .clk_cfg = LEDC_USE_APB_CLK,
    };
    if (ledc_timer_config(&timer) != ESP_OK) return false;
    const ledc_channel_config_t channel = {
        .gpio_num = CONFIG_DB_FAN_PWM_GATE_GPIO,
        .speed_mode = FAN_LEDC_MODE,
        .channel = FAN_LEDC_CHANNEL,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = FAN_LEDC_TIMER,
        .duty = plan->duty_counts,
        .hpoint = 0,
        .flags.output_invert = GATE_SINK_LEVEL ? 0 : 1,
    };
    ledc_channel_active = true;
    if (ledc_channel_config(&channel) != ESP_OK) return false;
    line_state = LINE_DRIVEN;
    return true;
}

static bool tach_clear(void *ctx) {
    (void)ctx;
    return tach_ready && pcnt_unit_clear_count(tach_unit) == ESP_OK;
}

static bool tach_read(void *ctx, int64_t *edge_count) {
    (void)ctx;
    int count = 0;
    if (!tach_ready || pcnt_unit_get_count(tach_unit, &count) != ESP_OK || count < 0) return false;
    *edge_count = count;
    return true;
}

static int64_t now_us(void *ctx) {
    (void)ctx;
    return esp_timer_get_time();
}

static bool hold_should_abort(void *ctx) {
    (void)ctx;
    return abort_requested && abort_requested();
}

static void sleep_ms(void *ctx, uint32_t ms) {
    (void)ctx;
    const TickType_t ticks = pdMS_TO_TICKS(ms);
    vTaskDelay(ticks ? ticks : 1);
}

static const db_fan_ops_t ops = {
    .release = release_line,
    .apply = apply_stimulus,
    .tach_clear = tach_clear,
    .tach_read = tach_read,
    .now_us = now_us,
    .should_abort = hold_should_abort,
    .sleep_ms = sleep_ms,
};

// Counts falling edges only, so edges equal tach pulses; the accumulating
// watch point at the 16-bit limit extends the hardware counter.
static bool tach_init(void) {
    const pcnt_unit_config_t unit_config = {
        .low_limit = -1,
        .high_limit = TACH_HIGH_LIMIT,
        .flags.accum_count = 1,
    };
    if (pcnt_new_unit(&unit_config, &tach_unit) != ESP_OK) return false;
#if CONFIG_DB_FAN_TACH_GLITCH_FILTER_NS > 0
    const pcnt_glitch_filter_config_t filter = {.max_glitch_ns = CONFIG_DB_FAN_TACH_GLITCH_FILTER_NS};
    if (pcnt_unit_set_glitch_filter(tach_unit, &filter) != ESP_OK) return false;
#endif
    const pcnt_chan_config_t channel_config = {.edge_gpio_num = CONFIG_DB_FAN_TACH_GPIO, .level_gpio_num = -1};
    pcnt_channel_handle_t channel = NULL;
    if (pcnt_new_channel(tach_unit, &channel_config, &channel) != ESP_OK ||
        pcnt_channel_set_edge_action(channel, PCNT_CHANNEL_EDGE_ACTION_HOLD, PCNT_CHANNEL_EDGE_ACTION_INCREASE) != ESP_OK)
        return false;
    // pcnt_new_channel enables the internal pull-up; apply the fixture's explicit choice.
    if (gpio_set_pull_mode(TACH_GPIO, TACH_INTERNAL_PULLUP ? GPIO_PULLUP_ONLY : GPIO_FLOATING) != ESP_OK) return false;
    return pcnt_unit_add_watch_point(tach_unit, TACH_HIGH_LIMIT) == ESP_OK && pcnt_unit_enable(tach_unit) == ESP_OK &&
           pcnt_unit_clear_count(tach_unit) == ESP_OK && pcnt_unit_start(tach_unit) == ESP_OK;
}

static void shutdown_release(void) { release_line(NULL); }

void fan_fixture_boot(void) {
    if (!db_fan_boot_release(&ops)) ESP_LOGE(TAG, "gate release could not be verified at boot");
    tach_ready = tach_init();
    if (!tach_ready) ESP_LOGE(TAG, "tach capture unavailable on GPIO%d", CONFIG_DB_FAN_TACH_GPIO);
    if (esp_register_shutdown_handler(shutdown_release) != ESP_OK) ESP_LOGW(TAG, "no shutdown release handler");
    ESP_LOGW(TAG, "BENCH FAN FIXTURE BUILD: gate GPIO%d (sink level %d), tach GPIO%d, line %s",
             CONFIG_DB_FAN_PWM_GATE_GPIO, GATE_SINK_LEVEL, CONFIG_DB_FAN_TACH_GPIO, line_state_name(line_state));
}

db_fan_hold_outcome_t fan_fixture_hold(const db_run_request_t *request, bool (*should_abort)(void),
                                       db_fan_hold_result_t *result) {
    abort_requested = should_abort;
    const db_fan_hold_outcome_t outcome =
        db_fan_hold(&ops, request->pwm_hz, request->sink_duty_tenths_pct, request->duration_ms, result);
    abort_requested = NULL;
    return outcome;
}

uint32_t fan_fixture_ppr(void) { return CONFIG_DB_FAN_TACH_PPR; }

void fan_fixture_describe(cJSON *parent) {
    cJSON *o = cJSON_AddObjectToObject(parent, "fan_fixture");
    cJSON_AddStringToObject(o, "stimulus", "pwm_sink_via_external_open_drain_stage");
    cJSON_AddStringToObject(o, "fan_response", "uncharacterized");
    cJSON_AddStringToObject(o, "line_state", line_state_name(line_state));
    cJSON_AddNumberToObject(o, "pwm_gate_gpio", CONFIG_DB_FAN_PWM_GATE_GPIO);
    cJSON_AddNumberToObject(o, "gate_sink_level", GATE_SINK_LEVEL);
    cJSON_AddNumberToObject(o, "pwm_hz_min", DB_FAN_PWM_HZ_MIN);
    cJSON_AddNumberToObject(o, "pwm_hz_max", DB_FAN_PWM_HZ_MAX);
    cJSON_AddNumberToObject(o, "tach_gpio", CONFIG_DB_FAN_TACH_GPIO);
    cJSON_AddStringToObject(o, "tach_edge", "falling");
    cJSON_AddBoolToObject(o, "tach_ready", tach_ready);
    cJSON_AddBoolToObject(o, "tach_internal_pullup", TACH_INTERNAL_PULLUP);
    cJSON_AddNumberToObject(o, "tach_glitch_filter_ns", CONFIG_DB_FAN_TACH_GLITCH_FILTER_NS);
    if (CONFIG_DB_FAN_TACH_PPR > 0) {
        cJSON_AddNumberToObject(o, "tach_ppr", CONFIG_DB_FAN_TACH_PPR);
        cJSON_AddStringToObject(o, "tach_ppr_evidence", CONFIG_DB_FAN_TACH_PPR_EVIDENCE);
    } else {
        cJSON_AddNullToObject(o, "tach_ppr");
    }
}

#endif // fixture configured

#endif
