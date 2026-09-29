#!/usr/bin/env bash
set -euo pipefail

# Usage: ci/build-esp32s3.sh <board> [experiment] [--expect-refusal]
#   board:       n8r8 | n16r8 | tinys3d
#   experiment:  baseline (default) | fan-characterization
#
# An image is one board profile plus one experiment profile. Each experiment
# layers sdkconfig.defaults.<experiment>; one that needs fixture wiring also
# layers the untracked sdkconfig.<experiment>.local. --expect-refusal builds
# the experiment WITHOUT its local overlay and passes only if the build stops
# naming every missing wiring setting.
board="${1:-n8r8}"
experiment="${2:-baseline}"
expect_refusal="${3:-}"
case "$board" in
    n8r8)
        defaults="sdkconfig.defaults"
        expect=("CONFIG_SPIRAM_MODE_OCT 1" "CONFIG_ESPTOOLPY_FLASHSIZE_8MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-n8r8"'
                "CONFIG_DB_RF_SWITCH_GPIO -1" "CONFIG_DB_BOARD_RESERVED_GPIO -1")
        ;;
    n16r8)
        defaults="sdkconfig.defaults;sdkconfig.defaults.n16r8"
        expect=("CONFIG_SPIRAM_MODE_OCT 1" "CONFIG_ESPTOOLPY_FLASHSIZE_16MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-n16r8"'
                "CONFIG_DB_RF_SWITCH_GPIO -1" "CONFIG_DB_BOARD_RESERVED_GPIO 48")
        ;;
    tinys3d)
        defaults="sdkconfig.defaults;sdkconfig.defaults.tinys3d"
        expect=("CONFIG_SPIRAM_MODE_QUAD 1" "CONFIG_ESPTOOLPY_FLASHSIZE_8MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-tinys3d"'
                "CONFIG_DB_RF_SWITCH_GPIO 38" "CONFIG_DB_BOARD_RESERVED_GPIO -1")
        ;;
    *)
        echo "unknown board profile: $board (expected n8r8, n16r8, or tinys3d)" >&2
        exit 2
        ;;
esac

# Non-baseline experiments, and what must be absent from every other image.
all_experiments=(fan-characterization)
declare -A experiment_symbol=([fan-characterization]="FAN_CHARACTERIZATION")
declare -A experiment_code=([fan-characterization]="ledc_|pcnt_|fan_characterization_")
declare -A experiment_entry=([fan-characterization]="fan_characterization_hold")
declare -A experiment_wiring=([fan-characterization]="CONFIG_DB_FAN_PWM_GATE_GPIO CONFIG_DB_FAN_GATE_SINK_LEVEL CONFIG_DB_FAN_TACH_GPIO")

case "$experiment" in
    baseline)
        expect+=("CONFIG_DB_EXPERIMENT_BASELINE 1")
        ;;
    fan-characterization)
        defaults="$defaults;sdkconfig.defaults.$experiment"
        expect+=("CONFIG_DB_EXPERIMENT_${experiment_symbol[$experiment]} 1")
        if [[ -z "$expect_refusal" ]]; then
            if [[ ! -f "sdkconfig.$experiment.local" ]]; then
                echo "$experiment needs sdkconfig.$experiment.local stating the wired fixture (docs/FAN_CHARACTERIZATION.md)" >&2
                exit 2
            fi
            defaults="$defaults;sdkconfig.$experiment.local"
        fi
        ;;
    *)
        echo "unknown experiment profile: $experiment (expected baseline or ${all_experiments[*]})" >&2
        exit 2
        ;;
esac
if [[ -n "$expect_refusal" && ( "$expect_refusal" != --expect-refusal || "$experiment" == baseline ) ]]; then
    echo "--expect-refusal applies only to an experiment that needs fixture wiring" >&2
    exit 2
fi

rm -f sdkconfig
idf.py -D SDKCONFIG_DEFAULTS="$defaults" fullclean
idf.py -D SDKCONFIG_DEFAULTS="$defaults" set-target esp32s3

if [[ -n "$expect_refusal" ]]; then
    if idf.py -D SDKCONFIG_DEFAULTS="$defaults" build > idf-build.log 2>&1; then
        echo "unconfigured $experiment build succeeded; it must refuse to build" >&2
        exit 1
    fi
    for setting in ${experiment_wiring[$experiment]}; do
        if ! grep -q "#error \"$experiment: set $setting" idf-build.log; then
            echo "unconfigured $experiment build did not name $setting" >&2
            exit 1
        fi
    done
    echo "$board/$experiment without wiring refused as expected"
    exit 0
fi

idf.py -D SDKCONFIG_DEFAULTS="$defaults" build 2>&1 | tee idf-build.log

if grep -Ei 'warning:|error:' idf-build.log; then
    echo "ESP-IDF build emitted a warning or error" >&2
    exit 1
fi

for line in "${expect[@]}"; do
    if ! grep -qF "#define $line" build/config/sdkconfig.h; then
        echo "$board/$experiment did not produce '#define $line'" >&2
        exit 1
    fi
done

nm_tool="${NM:-xtensa-esp32s3-elf-nm}"
# Fail rather than pass vacuously if the symbol table cannot be read.
symbols="$("$nm_tool" build/dragonbench.elf)"
if ! grep -q ' app_main$' <<< "$symbols"; then
    echo "could not read symbols from build/dragonbench.elf with $nm_tool" >&2
    exit 1
fi
for other in "${all_experiments[@]}"; do
    code="$(grep -E " (${experiment_code[$other]})" <<< "$symbols" || true)"
    if [[ "$other" == "$experiment" ]]; then
        if ! grep -q " ${experiment_entry[$other]}$" <<< "$code"; then
            echo "$board/$experiment does not link ${experiment_entry[$other]}" >&2
            exit 1
        fi
        continue
    fi
    if grep -q "CONFIG_DB_EXPERIMENT_${experiment_symbol[$other]}" build/config/sdkconfig.h; then
        echo "$board/$experiment also selected $other" >&2
        exit 1
    fi
    if [[ -n "$code" ]]; then
        echo "$board/$experiment links $other code:" >&2
        echo "$code" >&2
        exit 1
    fi
done
echo "$board/$experiment verified"
