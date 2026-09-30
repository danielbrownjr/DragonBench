#pragma once

// ESP32-S3 SoC target layer: the SoC facts the shared firmware reports or
// depends on. firmware/main selects firmware/targets/<IDF_TARGET>/include by
// the ESP-IDF build target, so a board profile can never change them.

#include "sdkconfig.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error "firmware/targets/esp32s3 selected for a build of another SoC target"
#endif

#define DB_SOC_TARGET "esp32s3"

// measurement_provenance sources for what this firmware measures on the SoC.
#define DB_SOC_TEMPERATURE_SOURCE "dut.esp32s3_temperature_sensor"
#define DB_SOC_WIFI_SOURCE "dut.esp32s3_wifi"
#define DB_SOC_PCNT_SOURCE "dut.esp32s3_pcnt"

// Station bands the SoC radio supports, as the setup page words it.
#define DB_SOC_STA_BANDS_TEXT "2.4 GHz"

// DB_FAN_PIN_RESERVED (db_fan.h) is the reviewed ESP32-S3 fixture pin map.
#define DB_SOC_FAN_FIXTURE_PIN_GUARDS 1
