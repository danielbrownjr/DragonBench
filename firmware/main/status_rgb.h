#pragma once

#include <stdbool.h>

// The board's onboard WS2812 LED as DragonBench's status light: solid green or
// off, nothing else. Both calls block until the LED has latched the new state.
// Without CONFIG_DB_STATUS_RGB_GPIO they do nothing.

// Configures the LED pins and turns the LED off. Call once, at boot.
void status_rgb_init(void);
// Solid green when true; off (and unpowered, where the board can) when false.
void status_rgb_set(bool green);
