#pragma once

// ESP32-C5 SoC target layer (see firmware/targets/esp32s3/include/db_soc.h).
// ESP32-C5 is a single-core RISC-V SoC with 2.4 GHz and 5 GHz Wi-Fi 6
// (ESP-IDF soc_caps.h: SOC_CPU_CORES_NUM 1, SOC_WIFI_SUPPORT_5G). ESP-IDF
// supports it as a full target from v5.5.1; see docs/TARGET_ESP32C5.md.

#include "sdkconfig.h"

#if !CONFIG_IDF_TARGET_ESP32C5
#error "firmware/targets/esp32c5 selected for a build of another SoC target"
#endif

#define DB_SOC_TARGET "esp32c5"

#define DB_SOC_TEMPERATURE_SOURCE "dut.esp32c5_temperature_sensor"
#define DB_SOC_WIFI_SOURCE "dut.esp32c5_wifi"

// The SoC supports 5 GHz; DragonBench has not yet shown a 5 GHz connection.
#define DB_SOC_STA_BANDS_TEXT "2.4 GHz or 5 GHz (5 GHz not yet validated on ESP32-C5)"

// No reviewed ESP32-C5 fixture pin map exists (GPIO7, for one, is a C5
// strapping pin), so the fan-characterization experiment refuses to build.
#define DB_SOC_FAN_FIXTURE_PIN_GUARDS 0
