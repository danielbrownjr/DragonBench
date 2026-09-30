#!/usr/bin/env bash
set -euo pipefail

# Usage: ci/build-esp32s3.sh <board> [experiment] [--expect-refusal]
# The ESP32-S3 lane of ci/build-firmware.sh, kept for existing commands and
# bench records: ci/build-esp32s3.sh n16r8 is ci/build-firmware.sh esp32s3 n16r8.
exec "$(dirname "${BASH_SOURCE[0]}")/build-firmware.sh" esp32s3 "${1:-n8r8}" "${@:2}"
