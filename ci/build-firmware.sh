#!/usr/bin/env bash
set -euo pipefail

# Usage: ci/build-firmware.sh <soc-target> <board> [experiment] [--expect-refusal]
#   soc-target:  esp32s3 (ESP-IDF 5.3.5) | esp32c5 (ESP-IDF 5.5.5)
#   board:       esp32s3: n8r8 | n16r8 | tinys3d
#                esp32c5: wroom1u-n32r8 (provisional)
#   experiment:  baseline (default) | fan-characterization (esp32s3 only)
#
# An image is one SoC target, one of its board profiles, and one experiment
# profile the board supports. ESP-IDF layers sdkconfig.defaults, then
# sdkconfig.defaults.<soc-target>, then the board's overlay. Each experiment
# layers sdkconfig.defaults.<experiment>; one that needs fixture wiring also
# layers the untracked sdkconfig.<experiment>.local. --expect-refusal builds
# the experiment WITHOUT its local overlay and passes only if the build stops
# naming every missing wiring setting.
#
# Every argument is validated before ESP-IDF runs: an unknown target, a board
# of another target, or an experiment the board does not support exits 2.
target="${1:-}"
board="${2:-}"
experiment="${3:-baseline}"
expect_refusal="${4:-}"

# The ESP-IDF release each SoC target builds with. ESP32-C5 is only a preview
# target before ESP-IDF 5.5.1, so it has its own lane; ESP32-S3 stays on 5.3.5.
case "$target" in
    esp32s3)
        idf_version="5.3.5"
        nm_default="xtensa-esp32s3-elf-nm"
        ;;
    esp32c5)
        idf_version="5.5.5"
        nm_default="riscv32-esp-elf-nm"
        ;;
    *)
        echo "unknown SoC target: ${target:-<none>} (expected esp32s3 or esp32c5)" >&2
        exit 2
        ;;
esac

case "$target/$board" in
    esp32s3/n8r8)
        defaults="sdkconfig.defaults"
        experiments="baseline fan-characterization"
        expect=("CONFIG_SPIRAM_MODE_OCT 1" "CONFIG_ESPTOOLPY_FLASHSIZE_8MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-n8r8"'
                "CONFIG_DB_RF_SWITCH_GPIO -1" "CONFIG_DB_STATUS_RGB_GPIO 48" "CONFIG_DB_STATUS_RGB_POWER_GPIO -1")
        ;;
    esp32s3/n16r8)
        defaults="sdkconfig.defaults;sdkconfig.defaults.n16r8"
        experiments="baseline fan-characterization"
        expect=("CONFIG_SPIRAM_MODE_OCT 1" "CONFIG_ESPTOOLPY_FLASHSIZE_16MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-n16r8"'
                "CONFIG_DB_RF_SWITCH_GPIO -1" "CONFIG_DB_STATUS_RGB_GPIO 48" "CONFIG_DB_STATUS_RGB_POWER_GPIO -1")
        ;;
    esp32s3/tinys3d)
        defaults="sdkconfig.defaults;sdkconfig.defaults.tinys3d"
        experiments="baseline fan-characterization"
        expect=("CONFIG_SPIRAM_MODE_QUAD 1" "CONFIG_ESPTOOLPY_FLASHSIZE_8MB 1" 'CONFIG_DB_TARGET_NAME "esp32s3-tinys3d"'
                "CONFIG_DB_RF_SWITCH_GPIO 38" "CONFIG_DB_STATUS_RGB_GPIO 18" "CONFIG_DB_STATUS_RGB_POWER_GPIO 17"
                "CONFIG_DB_STATUS_RGB_POWER_ACTIVE_LEVEL 1")
        ;;
    esp32c5/wroom1u-n32r8)
        defaults="sdkconfig.defaults;sdkconfig.defaults.wroom1u-n32r8"
        experiments="baseline"
        expect=("CONFIG_SPIRAM_MODE_QUAD 1" "CONFIG_ESPTOOLPY_FLASHSIZE_8MB 1" 'CONFIG_DB_TARGET_NAME "esp32c5-wroom1u-n32r8"'
                "CONFIG_DB_BOARD_PROFILE_PROVISIONAL 1" "CONFIG_DB_BOARD_FLASH_CLAIM_MB 32" "CONFIG_DB_BOARD_PSRAM_CLAIM_MB 8"
                'CONFIG_DB_BOARD_MEMORY_CLAIM_SOURCE "expected_from_seller"' "CONFIG_SPIRAM_IGNORE_NOTFOUND 1"
                "CONFIG_DB_RF_SWITCH_GPIO -1" "CONFIG_DB_STATUS_RGB_GPIO -1" "CONFIG_DB_STATUS_RGB_POWER_GPIO -1")
        ;;
    *)
        echo "unknown $target board profile: ${board:-<none>}" \
             "(esp32s3: n8r8, n16r8, tinys3d; esp32c5: wroom1u-n32r8)" >&2
        exit 2
        ;;
esac
expect+=("CONFIG_IDF_TARGET \"$target\"")

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
        ;;
    *)
        echo "unknown experiment profile: $experiment (expected baseline or ${all_experiments[*]})" >&2
        exit 2
        ;;
esac
if [[ " $experiments " != *" $experiment "* ]]; then
    echo "$target/$board does not support the $experiment experiment profile (supported: $experiments)" >&2
    exit 2
fi
if [[ -n "$expect_refusal" && ( "$expect_refusal" != --expect-refusal || "$experiment" == baseline ) ]]; then
    echo "--expect-refusal applies only to an experiment that needs fixture wiring" >&2
    exit 2
fi
if [[ "$experiment" != baseline && -z "$expect_refusal" ]]; then
    if [[ ! -f "sdkconfig.$experiment.local" ]]; then
        echo "$experiment needs sdkconfig.$experiment.local stating the wired fixture (docs/FAN_CHARACTERIZATION.md)" >&2
        exit 2
    fi
    defaults="$defaults;sdkconfig.$experiment.local"
fi

# The lane must match: a C5 image from the S3 lane's ESP-IDF (or the reverse)
# is refused rather than built with an unsupported or preview toolchain.
actual_idf="$(idf.py --version 2>/dev/null || true)"
if [[ "$actual_idf" != *"v$idf_version"* ]]; then
    echo "$target builds with ESP-IDF $idf_version; this environment has: ${actual_idf:-no idf.py}" >&2
    exit 2
fi

# Each SoC target builds from its committed Component Manager lockfile (see
# CMakeLists.txt). A missing one would be re-resolved silently and leave the
# checkout dirty, so refuse instead.
lockfile="dependencies.lock"
[[ "$target" == esp32s3 ]] || lockfile="dependencies.lock.$target"
if [[ ! -f "$lockfile" ]]; then
    echo "$target builds from the committed $lockfile, which is missing (docs/TARGET_ESP32C5.md)" >&2
    exit 2
fi

rm -f sdkconfig
idf.py -D SDKCONFIG_DEFAULTS="$defaults" fullclean
idf.py -D SDKCONFIG_DEFAULTS="$defaults" set-target "$target" 2>&1 | tee idf-configure.log
# Settings the target does not know (a stale or other-SoC default) are only
# warned about by the configuration step; treat them as defects too.
if grep -Ei 'warning:|error:' idf-configure.log; then
    echo "ESP-IDF configuration emitted a warning or error" >&2
    exit 1
fi

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
    echo "$target/$board/$experiment without wiring refused as expected"
    exit 0
fi

idf.py -D SDKCONFIG_DEFAULTS="$defaults" build 2>&1 | tee idf-build.log

if grep -Ei 'warning:|error:' idf-build.log; then
    echo "ESP-IDF build emitted a warning or error" >&2
    exit 1
fi

for line in "${expect[@]}"; do
    if ! grep -qF "#define $line" build/config/sdkconfig.h; then
        echo "$target/$board/$experiment did not produce '#define $line'" >&2
        exit 1
    fi
done

nm_tool="${NM:-$nm_default}"
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
            echo "$target/$board/$experiment does not link ${experiment_entry[$other]}" >&2
            exit 1
        fi
        continue
    fi
    if grep -q "CONFIG_DB_EXPERIMENT_${experiment_symbol[$other]}" build/config/sdkconfig.h; then
        echo "$target/$board/$experiment also selected $other" >&2
        exit 1
    fi
    if [[ -n "$code" ]]; then
        echo "$target/$board/$experiment links $other code:" >&2
        echo "$code" >&2
        exit 1
    fi
done

# No other SoC's identity may be compiled into the image.
for soc in esp32s3 esp32c5; do
    [[ "$soc" == "$target" ]] && continue
    if grep -qF "$soc" build/config/sdkconfig.h || grep -aqF "$soc" build/dragonbench.bin; then
        echo "$target/$board/$experiment image names $soc" >&2
        exit 1
    fi
done
echo "$target/$board/$experiment verified"
