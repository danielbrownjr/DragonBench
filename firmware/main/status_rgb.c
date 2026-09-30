#include "status_rgb.h"

#include "sdkconfig.h"

#if CONFIG_DB_STATUS_RGB_GPIO >= 0

#include <stdint.h>

#include "driver/gpio.h"
#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "esp_rom_sys.h"

#define TAG "status_rgb"
// 10 MHz: 0.1 us per RMT tick.
#define RMT_RESOLUTION_HZ 10000000
// WS2812 bit timing as in the ESP-IDF RMT led_strip example: a 0 is 0.3 us
// high then 0.9 us low, a 1 is 0.9 us high then 0.3 us low.
#define SHORT_TICKS 3
#define LONG_TICKS 9
// Low time after a frame before the LED shows it; WS2812B V5 needs > 280 us.
#define LATCH_US 300
// Time for a GPIO-powered LED to start after its supply is switched on.
#define POWER_UP_US 1000
// Green channel level (of 255): visible, and a small fixed load.
#define GREEN_LEVEL 16

static rmt_channel_handle_t channel;
static rmt_encoder_handle_t encoder;
static bool available;

static void set_power(bool on) {
#if CONFIG_DB_STATUS_RGB_POWER_GPIO >= 0
    const int active = CONFIG_DB_STATUS_RGB_POWER_ACTIVE_LEVEL;
    gpio_set_level(CONFIG_DB_STATUS_RGB_POWER_GPIO, on ? active : !active);
#else
    (void)on;
#endif
}

// Sends one GRB frame and waits until the LED has latched it.
static void send_frame(uint8_t green) {
    const uint8_t grb[3] = {green, 0, 0};
    const rmt_transmit_config_t tx = {.loop_count = 0, .flags.eot_level = 0};
    if (rmt_transmit(channel, encoder, grb, sizeof(grb), &tx) == ESP_OK)
        rmt_tx_wait_all_done(channel, 10);
    esp_rom_delay_us(LATCH_US);
}

void status_rgb_init(void) {
#if CONFIG_DB_STATUS_RGB_POWER_GPIO >= 0
    gpio_reset_pin(CONFIG_DB_STATUS_RGB_POWER_GPIO);
    gpio_set_direction(CONFIG_DB_STATUS_RGB_POWER_GPIO, GPIO_MODE_OUTPUT);
    set_power(false);
#endif
    const rmt_tx_channel_config_t config = {
        .gpio_num = CONFIG_DB_STATUS_RGB_GPIO,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = RMT_RESOLUTION_HZ,
        .mem_block_symbols = 48, // one frame is 24 symbols
        .trans_queue_depth = 1,
    };
    const rmt_bytes_encoder_config_t bits = {
        .bit0 = {.level0 = 1, .duration0 = SHORT_TICKS, .level1 = 0, .duration1 = LONG_TICKS},
        .bit1 = {.level0 = 1, .duration0 = LONG_TICKS, .level1 = 0, .duration1 = SHORT_TICKS},
        .flags.msb_first = 1,
    };
    available = rmt_new_tx_channel(&config, &channel) == ESP_OK &&
                rmt_new_bytes_encoder(&bits, &encoder) == ESP_OK && rmt_enable(channel) == ESP_OK;
    if (!available) {
        ESP_LOGW(TAG, "status RGB unavailable on GPIO%d", CONFIG_DB_STATUS_RGB_GPIO);
        return;
    }
#if CONFIG_DB_STATUS_RGB_POWER_GPIO < 0
    // Always powered: blank it. A GPIO-powered LED is already unpowered, and
    // clocking data into it would feed it through its data input.
    send_frame(0);
#endif
}

void status_rgb_set(bool green) {
    if (!available) return;
    if (green) {
        set_power(true);
#if CONFIG_DB_STATUS_RGB_POWER_GPIO >= 0
        esp_rom_delay_us(POWER_UP_US);
#endif
        send_frame(GREEN_LEVEL);
    } else {
        // Dark first, so the data line is idle low before the supply drops.
        send_frame(0);
        set_power(false);
    }
}

#else

void status_rgb_init(void) {}
void status_rgb_set(bool green) { (void)green; }

#endif
