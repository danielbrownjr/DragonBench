#!/usr/bin/env bash
set -euo pipefail

# Usage: ci/build-esp32s3.sh [n8r8|tinys3d] [fanfixture|fanfixture-unconfigured]
#
# Without a second argument this is a normal profile, which must contain no
# fan-stimulus code. "fanfixture" layers the bench fan-fixture overlay plus the
# untracked sdkconfig.fanfixture.local that states the wired GPIOs.
# "fanfixture-unconfigured" proves that the overlay alone refuses to build.
profile="${1:-n8r8}"
fixture="${2:-}"
case "$profile" in
    n8r8)
        defaults="sdkconfig.defaults"
        expect=("CONFIG_SPIRAM_MODE_OCT 1" 'CONFIG_DB_TARGET_NAME "esp32s3-n8r8"' "CONFIG_DB_RF_SWITCH_GPIO -1")
        ;;
    tinys3d)
        defaults="sdkconfig.defaults;sdkconfig.defaults.tinys3d"
        expect=("CONFIG_SPIRAM_MODE_QUAD 1" 'CONFIG_DB_TARGET_NAME "esp32s3-tinys3d"' "CONFIG_DB_RF_SWITCH_GPIO 38")
        ;;
    *)
        echo "unknown board profile: $profile (expected n8r8 or tinys3d)" >&2
        exit 2
        ;;
esac
case "$fixture" in
    "") ;;
    fanfixture)
        if [[ ! -f sdkconfig.fanfixture.local ]]; then
            echo "fanfixture needs sdkconfig.fanfixture.local stating the wired fixture (docs/FAN_FIXTURE.md)" >&2
            exit 2
        fi
        defaults="$defaults;sdkconfig.defaults.fanfixture;sdkconfig.fanfixture.local"
        expect+=("CONFIG_DB_FAN_FIXTURE 1")
        ;;
    fanfixture-unconfigured)
        defaults="$defaults;sdkconfig.defaults.fanfixture"
        ;;
    *)
        echo "unknown fixture option: $fixture (expected fanfixture or fanfixture-unconfigured)" >&2
        exit 2
        ;;
esac

rm -f sdkconfig
idf.py -D SDKCONFIG_DEFAULTS="$defaults" fullclean
idf.py -D SDKCONFIG_DEFAULTS="$defaults" set-target esp32s3

if [[ "$fixture" == fanfixture-unconfigured ]]; then
    if idf.py -D SDKCONFIG_DEFAULTS="$defaults" build > idf-build.log 2>&1; then
        echo "unconfigured fan-fixture build succeeded; it must refuse to build" >&2
        exit 1
    fi
    for setting in CONFIG_DB_FAN_PWM_GATE_GPIO CONFIG_DB_FAN_GATE_SINK_LEVEL CONFIG_DB_FAN_TACH_GPIO; do
        if ! grep -q "#error \"Fan fixture: set $setting" idf-build.log; then
            echo "unconfigured fan-fixture build did not name $setting" >&2
            exit 1
        fi
    done
    echo "profile $profile unconfigured fan fixture refused as expected"
    exit 0
fi

idf.py -D SDKCONFIG_DEFAULTS="$defaults" build 2>&1 | tee idf-build.log

if grep -Ei 'warning:|error:' idf-build.log; then
    echo "ESP-IDF build emitted a warning or error" >&2
    exit 1
fi

for line in "${expect[@]}"; do
    if ! grep -qF "#define $line" build/config/sdkconfig.h; then
        echo "profile $profile did not produce '#define $line'" >&2
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
stimulus_symbols="$(grep -E ' (ledc_|pcnt_|fan_fixture_)' <<< "$symbols" || true)"
if [[ -z "$fixture" ]]; then
    if grep -q "CONFIG_DB_FAN_FIXTURE" build/config/sdkconfig.h; then
        echo "normal profile $profile enabled the fan fixture" >&2
        exit 1
    fi
    if [[ -n "$stimulus_symbols" ]]; then
        echo "normal profile $profile links fan-stimulus code:" >&2
        echo "$stimulus_symbols" >&2
        exit 1
    fi
elif ! grep -q ' fan_fixture_hold$' <<< "$stimulus_symbols"; then
    echo "fan-fixture profile $profile does not link fan_fixture_hold" >&2
    exit 1
fi
echo "profile $profile${fixture:+ ($fixture)} verified"
