# db_check_board_target(<idf_target> <board_profile>)
#
# Fails the configure step unless <board_profile> (CONFIG_DB_TARGET_NAME) is a
# board of the SoC being built: it must be "<idf_target>-<board>". This keeps
# an image from reporting a board of another SoC, for example an ESP32-S3
# identity on an ESP32-C5 build. An empty profile means no board overlay was
# layered; that is refused too rather than guessed.
function(db_check_board_target idf_target board_profile)
    if(board_profile STREQUAL "")
        message(FATAL_ERROR "DragonBench: no board profile for ${idf_target}; layer a board's sdkconfig.defaults overlay (ci/build-firmware.sh)")
    endif()
    string(LENGTH "${idf_target}-" prefix_length)
    string(SUBSTRING "${board_profile}" 0 ${prefix_length} prefix)
    string(LENGTH "${board_profile}" profile_length)
    if(NOT prefix STREQUAL "${idf_target}-" OR profile_length EQUAL prefix_length)
        message(FATAL_ERROR "DragonBench: board profile '${board_profile}' is not an ${idf_target} board")
    endif()
endfunction()

# cmake -DIDF_TARGET=<t> -DBOARD_PROFILE=<b> -P board_target_check.cmake
if(CMAKE_SCRIPT_MODE_FILE STREQUAL CMAKE_CURRENT_LIST_FILE)
    db_check_board_target("${IDF_TARGET}" "${BOARD_PROFILE}")
endif()
