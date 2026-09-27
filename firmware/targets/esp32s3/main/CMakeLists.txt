idf_component_register(
    SRCS "main.c" "fan_characterization.c"
    INCLUDE_DIRS "."
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
        esp_driver_tsens
        esp_driver_gpio
        esp_driver_ledc
        esp_driver_pcnt
        esp_timer
        json
)
