# SoC target layer: firmware/targets/<IDF_TARGET>/include/db_soc.h.
set(soc_include "${CMAKE_CURRENT_LIST_DIR}/../targets/${IDF_TARGET}/include")
if(NOT EXISTS "${soc_include}/db_soc.h")
    message(FATAL_ERROR "DragonBench has no SoC target layer for ${IDF_TARGET} (firmware/targets/${IDF_TARGET})")
endif()
include("${CMAKE_CURRENT_LIST_DIR}/board_target_check.cmake")
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    db_check_board_target("${IDF_TARGET}" "${CONFIG_DB_TARGET_NAME}")
endif()

idf_component_register(
    SRCS "main.c" "fan_characterization.c" "status_rgb.c"
    INCLUDE_DIRS "."
    PRIV_INCLUDE_DIRS "${soc_include}"
    REQUIRES
        common
        esp_event
        esp_http_server
        esp_netif
        esp_wifi
        nvs_flash
        mdns
        app_update
        esp_partition
        esp_psram
        spi_flash
        esp_driver_tsens
        esp_driver_gpio
        esp_driver_ledc
        esp_driver_pcnt
        esp_driver_rmt
        esp_timer
        json
)

# Source revision, regenerated on every build (see build_provenance.cmake).
idf_build_get_property(project_dir PROJECT_DIR)
set(provenance_header "${CMAKE_CURRENT_BINARY_DIR}/provenance/db_build_provenance.h")
add_custom_target(db_build_provenance
    COMMAND ${CMAKE_COMMAND} -DSOURCE_DIR=${project_dir} -DOUTPUT=${provenance_header}
            -P ${CMAKE_CURRENT_LIST_DIR}/build_provenance.cmake
    BYPRODUCTS ${provenance_header}
    COMMENT "Recording DragonBench source revision"
    VERBATIM)
add_dependencies(${COMPONENT_LIB} db_build_provenance)
target_include_directories(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/provenance")
