cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS firmware/common firmware/main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# One Component Manager lockfile per SoC target: each target builds with its
# own ESP-IDF version, and the manager rewrites a lockfile resolved for another
# target or IDF. ESP32-S3 keeps the original dependencies.lock.
if(NOT IDF_TARGET STREQUAL "esp32s3")
    idf_build_set_property(DEPENDENCIES_LOCK "${CMAKE_CURRENT_LIST_DIR}/dependencies.lock.${IDF_TARGET}")
endif()
project(dragonbench)
