"""ESP32-C5 SoC target and its provisional WROOM-1U/N32R8 board profile.

The C5 is a second SoC target, not an ESP32-S3 variant: it has its own SoC
target layer (firmware/targets/esp32c5), SoC defaults (sdkconfig.defaults.esp32c5),
ESP-IDF lane (5.5.5), and board registry entry. These tests pin what the
provisional board profile claims, what it refuses, and that no ESP32-S3
identity leaks into it (or the reverse).
"""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

# Module imports, so this file does not re-collect their test classes.
import test_board_profiles as boards
import test_experiment_profiles as profiles

ROOT = Path(__file__).parents[1]
MAIN_C = ROOT / "firmware/main/main.c"
FIXTURE_C = ROOT / "firmware/main/fan_characterization.c"
KCONFIG = ROOT / "firmware/main/Kconfig.projbuild"
BOARD_CHECK = ROOT / "firmware/main/board_target_check.cmake"
BUILD_SCRIPT = ROOT / "ci/build-firmware.sh"
C5_SOC_H = ROOT / "firmware/targets/esp32c5/include/db_soc.h"
S3_SOC_H = ROOT / "firmware/targets/esp32s3/include/db_soc.h"
BOARD = "wroom1u-n32r8"
IDENTITY = "esp32c5-wroom1u-n32r8"


def c5_settings():
    """The provisional board's settings as ESP-IDF layers them for esp32c5."""
    return boards.resolved(BOARD, target="esp32c5")


class C5BoardProfileTests(unittest.TestCase):
    def test_c5_has_exactly_one_provisional_board(self):
        self.assertEqual(profiles.board_profiles("esp32c5"),
                         {BOARD: ["sdkconfig.defaults", "sdkconfig.defaults.wroom1u-n32r8"]})
        self.assertEqual(profiles.idf_layers("esp32c5", profiles.board_profiles("esp32c5")[BOARD]),
                         ["sdkconfig.defaults", "sdkconfig.defaults.esp32c5", "sdkconfig.defaults.wroom1u-n32r8"])

    def test_identity_and_provisional_status(self):
        settings = c5_settings()
        self.assertEqual(settings["CONFIG_DB_TARGET_NAME"], f'"{IDENTITY}"')
        self.assertEqual(settings["CONFIG_DB_BOARD_PROFILE_PROVISIONAL"], "y")
        for board in profiles.board_profiles("esp32s3"):
            self.assertNotIn("CONFIG_DB_BOARD_PROFILE_PROVISIONAL", boards.resolved(board), board)

    def test_memory_is_a_seller_claim_not_a_configuration(self):
        settings = c5_settings()
        self.assertEqual(settings["CONFIG_DB_BOARD_FLASH_CLAIM_MB"], "32")
        self.assertEqual(settings["CONFIG_DB_BOARD_PSRAM_CLAIM_MB"], "8")
        self.assertEqual(settings["CONFIG_DB_BOARD_MEMORY_CLAIM_SOURCE"], '"expected_from_seller"')
        # The image header does not assert the claimed 32 MB: a smaller chip
        # must still boot and report its measured size.
        self.assertEqual(boards._selected(settings, "CONFIG_ESPTOOLPY_FLASHSIZE_",
                                          ("2MB", "4MB", "8MB", "16MB", "32MB")), "8MB")
        # Missing PSRAM is reported, not a panic.
        self.assertEqual(settings["CONFIG_SPIRAM"], "y")
        self.assertEqual(settings["CONFIG_SPIRAM_IGNORE_NOTFOUND"], "y")

    def test_psram_is_quad_the_only_c5_mode(self):
        settings = c5_settings()
        self.assertEqual(boards._selected(settings, "CONFIG_SPIRAM_MODE_", ("QUAD", "OCT")), "QUAD")
        self.assertEqual(settings.get("CONFIG_SPIRAM_SPEED_40M"), "y")
        self.assertNotIn("CONFIG_SPIRAM_SPEED_80M", settings)

    def test_no_board_owned_gpio_is_claimed(self):
        # No status RGB, RF switch, or fixture pin is established for this carrier.
        settings = c5_settings()
        for name in ("DB_RF_SWITCH_GPIO", "DB_STATUS_RGB_GPIO", "DB_STATUS_RGB_POWER_GPIO"):
            self.assertEqual(int(settings[f"CONFIG_{name}"]), -1, name)
        for layer in ("sdkconfig.defaults.esp32c5", "sdkconfig.defaults.wroom1u-n32r8"):
            self.assertNotRegex((ROOT / layer).read_text(), r"(?m)^CONFIG_DB_\w*GPIO", layer)

    def test_gpio_settings_are_limited_to_c5_pads(self):
        # ESP32-C5 has GPIO0-GPIO28 (ESP-IDF soc_caps.h SOC_GPIO_PIN_COUNT 29).
        kconfig = KCONFIG.read_text()
        s3 = kconfig.count("range -1 48 if IDF_TARGET_ESP32S3")
        c5 = kconfig.count("range -1 28 if IDF_TARGET_ESP32C5")
        self.assertEqual(s3, 5)
        self.assertEqual(c5, s3)
        self.assertNotRegex(kconfig, r"(?m)^    range -1 48$")

    def test_partition_table_fits_every_configured_flash_header(self):
        # The shared table ends below 8 MB, the C5 image header size; its
        # offsets sit above the C5 bootloader (0x2000) and partition table (0x8000).
        first = None
        for line in (ROOT / "partitions.csv").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            offset = int(line.split(",")[3], 0)
            first = offset if first is None else min(first, offset)
        self.assertGreaterEqual(first, 0x9000)


class C5SocTargetTests(unittest.TestCase):
    def test_soc_layer_names_only_its_own_target(self):
        header = C5_SOC_H.read_text()
        self.assertIn('#define DB_SOC_TARGET "esp32c5"', header)
        self.assertIn("#if !CONFIG_IDF_TARGET_ESP32C5", header)
        self.assertNotIn("esp32s3", header.lower().replace("firmware/targets/esp32s3", ""))
        self.assertIn('#define DB_SOC_TARGET "esp32s3"', S3_SOC_H.read_text())
        self.assertNotIn("esp32c5", S3_SOC_H.read_text().lower())

    def test_soc_defaults_and_board_overlay_name_no_s3(self):
        for layer in ("sdkconfig.defaults.esp32c5", "sdkconfig.defaults.wroom1u-n32r8"):
            self.assertNotIn("esp32s3", (ROOT / layer).read_text().lower(), layer)
        self.assertNotIn("esp32c5", (ROOT / "sdkconfig.defaults.esp32s3").read_text().lower())

    def test_shared_firmware_names_no_soc(self):
        # SoC names reach the image only through db_soc.h, chosen by IDF_TARGET.
        for path in list((ROOT / "firmware/main").glob("*.[ch]")) + list((ROOT / "firmware/common").rglob("*.[ch]")):
            text = path.read_text().lower()
            for soc in ("esp32s3", "esp32c5"):
                self.assertNotIn(f'"{soc}', text, path)
                self.assertNotIn(f"dut.{soc}", text, path)
        self.assertIn('cJSON_AddStringToObject(o, "soc_target", DB_SOC_TARGET);', MAIN_C.read_text())

    def test_soc_layer_is_selected_by_the_build_target(self):
        cmake = (ROOT / "firmware/main/CMakeLists.txt").read_text()
        self.assertIn('"${CMAKE_CURRENT_LIST_DIR}/../targets/${IDF_TARGET}/include"', cmake)
        self.assertIn("has no SoC target layer", cmake)
        self.assertIn('db_check_board_target("${IDF_TARGET}" "${CONFIG_DB_TARGET_NAME}")', cmake)

    def test_only_esp32s3_has_a_default_board(self):
        block = re.search(r"config DB_TARGET_NAME\n((?:    .*\n|\n)*?)config ", KCONFIG.read_text()).group(1)
        self.assertEqual(re.findall(r"^    default (.*)$", block, re.M),
                         ['"esp32s3-n8r8" if IDF_TARGET_ESP32S3', '""'])

    def test_landing_page_does_not_hard_code_a_target(self):
        for page in (MAIN_C.read_text(), (ROOT / "web/index.html").read_text()):
            self.assertIn("Target: &mdash; &middot;", page)
            self.assertNotIn("Target: esp32s3", page)

    def test_each_soc_target_has_its_own_component_lockfile(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        self.assertIn('if(NOT IDF_TARGET STREQUAL "esp32s3")', cmake)
        self.assertIn('DEPENDENCIES_LOCK "${CMAKE_CURRENT_LIST_DIR}/dependencies.lock.${IDF_TARGET}"', cmake)
        self.assertIn("target: esp32s3", (ROOT / "dependencies.lock").read_text())


class C5CapabilityTests(unittest.TestCase):
    def test_c5_board_supports_baseline_only(self):
        self.assertEqual(profiles.board_experiments("esp32c5", BOARD), ["baseline"])
        for board in profiles.board_profiles("esp32s3"):
            self.assertIn("fan-characterization", profiles.board_experiments("esp32s3", board))

    def test_fan_fixture_refuses_socs_without_reviewed_pin_guards(self):
        self.assertIn("#define DB_SOC_FAN_FIXTURE_PIN_GUARDS 0", C5_SOC_H.read_text())
        self.assertIn("#define DB_SOC_FAN_FIXTURE_PIN_GUARDS 1", S3_SOC_H.read_text())
        source = FIXTURE_C.read_text()
        refusal = source.index("#if !DB_SOC_FAN_FIXTURE_PIN_GUARDS")
        self.assertLess(source.index("#if DB_EXPERIMENT_FAN_CHARACTERIZATION"), refusal)
        self.assertLess(refusal, source.index("#if CONFIG_DB_FAN_PWM_GATE_GPIO < 0"))
        self.assertIn('#error "fan-characterization: not supported on this SoC target', source)

    def test_fan_hold_is_not_advertised_without_the_fan_profile(self):
        # db_workload_supported(DB_FAN_PWM_HOLD) is the experiment macro, which a
        # C5 image cannot select (above), so the registry reports it unsupported.
        self.assertIn("return DB_EXPERIMENT_FAN_CHARACTERIZATION;", (ROOT / "firmware/common/db_run.c").read_text())
        self.assertIn('"requires fan-characterization experiment profile"', MAIN_C.read_text())

    def test_no_product_or_radio_stack_capability_is_added(self):
        text = "\n".join(p.read_text() for p in (ROOT / "firmware").rglob("*.[ch]")).lower()
        for stack in ("zigbee", "openthread", "esp_ieee802154", "nimble", "esp_bt", "matter"):
            self.assertNotIn(stack, text, stack)
        requires = (ROOT / "firmware/main/CMakeLists.txt").read_text()
        for component in ("bt", "ieee802154", "openthread"):
            self.assertNotRegex(requires, rf"(?m)^\s+{component}$", component)

    def test_memory_claim_is_never_reported_as_measured(self):
        body = MAIN_C.read_text()
        memory = body[body.index("static void add_memory"):body.index("static void measure_memory")]
        self.assertIn('"board_claim"', memory)
        self.assertIn("CONFIG_DB_BOARD_MEMORY_CLAIM_SOURCE", memory)
        self.assertIn("#if CONFIG_DB_BOARD_FLASH_CLAIM_MB > 0 || CONFIG_DB_BOARD_PSRAM_CLAIM_MB > 0", memory)
        # No reported key or value calls the claim validated or verified.
        self.assertNotRegex(memory.lower(), r'"[^"\n]*(validated|verified)[^"\n]*"')
        measure = body[body.index("static void measure_memory"):]
        self.assertIn("esp_flash_get_physical_size(NULL, &flash_detected_bytes)", measure)
        self.assertIn("esp_psram_get_size()", measure)

    def test_dual_band_radio_does_not_use_single_band_protocol_getter(self):
        # esp_wifi_get_protocol() is ESP_ERR_NOT_SUPPORTED in 2.4 + 5 GHz band
        # mode; on a dual-band SoC it would fail AP start-up.
        source = MAIN_C.read_text()
        start = source[source.index("static bool start_wifi(void)"):source.index("static void antenna_init")]
        guarded = start[start.index("#if SOC_WIFI_SUPPORT_5G"):start.index("#else", start.index("#if SOC_WIFI_SUPPORT_5G"))]
        self.assertIn("esp_wifi_get_protocols(WIFI_IF_AP, &protocols)", guarded)
        self.assertNotIn("esp_wifi_get_protocol(WIFI_IF_AP", guarded)
        self.assertIn('"sta_band", db_wifi_band_name(sta_channel)', source)


class C5ProtocolTests(unittest.TestCase):
    def test_protocol_knows_the_c5_board_and_soc(self):
        schema = json.loads((ROOT / "protocol/event.schema.json").read_text())
        self.assertIn(IDENTITY, schema["properties"]["target"]["enum"])
        openapi = (ROOT / "protocol/openapi.yaml").read_text()
        self.assertIn("soc_target: {type: string, enum: [esp32s3, esp32c5]}", openapi)
        self.assertRegex(openapi, r"board_profile: \{type: string, enum: \[[^\]]*esp32c5-wroom1u-n32r8")
        self.assertIn("board_profile_provisional: {type: boolean}", openapi)
        self.assertIn("source: {type: string, example: expected_from_seller}", openapi)

    def test_every_board_identity_starts_with_its_soc_target(self):
        for target in profiles.soc_targets():
            for board in profiles.board_profiles(target):
                name = boards.resolved(board, target=target).get("CONFIG_DB_TARGET_NAME", '"esp32s3-n8r8"')
                self.assertTrue(name.strip('"').startswith(f"{target}-"), (target, board, name))


@unittest.skipUnless(shutil.which("cmake"), "needs cmake")
class BoardTargetCheckTests(unittest.TestCase):
    """Runs the real configure-time board/target check (board_target_check.cmake)."""

    def check(self, target, board_profile):
        result = subprocess.run(["cmake", f"-DIDF_TARGET={target}", f"-DBOARD_PROFILE={board_profile}",
                                 "-P", str(BOARD_CHECK)], capture_output=True, text=True)
        return result.returncode, result.stderr

    def test_accepts_boards_of_the_target(self):
        self.assertEqual(self.check("esp32c5", IDENTITY)[0], 0)
        for board in ("esp32s3-n8r8", "esp32s3-n16r8", "esp32s3-tinys3d"):
            self.assertEqual(self.check("esp32s3", board)[0], 0, board)

    def test_rejects_an_s3_board_on_c5_and_the_reverse(self):
        code, err = self.check("esp32c5", "esp32s3-n16r8")
        self.assertNotEqual(code, 0)
        self.assertIn("'esp32s3-n16r8' is not an esp32c5 board", err)
        code, err = self.check("esp32s3", IDENTITY)
        self.assertNotEqual(code, 0)
        self.assertIn(f"'{IDENTITY}' is not an esp32s3 board", err)

    def test_rejects_a_missing_or_bare_board(self):
        code, err = self.check("esp32c5", "")
        self.assertNotEqual(code, 0)
        self.assertIn("no board profile for esp32c5", err)
        self.assertNotEqual(self.check("esp32c5", "esp32c5-")[0], 0)
        self.assertNotEqual(self.check("esp32c5", "esp32c5")[0], 0)
        self.assertNotEqual(self.check("esp32c5", "xesp32c5-wroom1u-n32r8")[0], 0)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class BuildScriptRefusalTests(unittest.TestCase):
    """ci/build-firmware.sh must refuse bad combinations before ESP-IDF runs."""

    @classmethod
    def setUpClass(cls):
        # A fake idf.py that records any call, so a refusal is proven to happen
        # before configuration and the lane check can be exercised.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.tmp.name)
        cls.calls = cls.bin / "calls"
        fake = cls.bin / "idf.py"
        fake.write_text('#!/usr/bin/env bash\nif [[ "$1" == --version ]]; then echo "ESP-IDF $FAKE_IDF"; exit 0; fi\n'
                        f'echo "$*" >> "{cls.calls}"\nexit 1\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_script(self, *args, idf="v5.5.5"):
        self.calls.unlink(missing_ok=True)
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_IDF": idf}
        result = subprocess.run(["bash", str(BUILD_SCRIPT), *args], cwd=self.tmp.name, env=env,
                                capture_output=True, text=True)
        return result.returncode, result.stderr, self.calls.exists()

    def assertRefused(self, args, message, idf="v5.5.5"):
        code, err, configured = self.run_script(*args, idf=idf)
        self.assertEqual(code, 2, err)
        self.assertIn(message, err)
        self.assertFalse(configured, f"{args} ran ESP-IDF before refusing")

    def test_rejects_s3_board_on_c5(self):
        self.assertRefused(["esp32c5", "n16r8"], "unknown esp32c5 board profile: n16r8")

    def test_rejects_c5_board_on_s3(self):
        self.assertRefused(["esp32s3", BOARD], f"unknown esp32s3 board profile: {BOARD}", idf="v5.3.5")

    def test_rejects_unknown_c5_board_and_unknown_target(self):
        self.assertRefused(["esp32c5", "devkitc-1"], "unknown esp32c5 board profile: devkitc-1")
        self.assertRefused(["esp32c5"], "unknown esp32c5 board profile: <none>")
        self.assertRefused(["esp32", "n8r8"], "unknown SoC target: esp32")
        self.assertRefused([], "unknown SoC target: <none>")

    def test_rejects_fan_characterization_on_c5(self):
        self.assertRefused(["esp32c5", BOARD, "fan-characterization"],
                           "does not support the fan-characterization experiment profile")
        self.assertRefused(["esp32c5", BOARD, "fan-characterization", "--expect-refusal"],
                           "does not support the fan-characterization experiment profile")

    def test_rejects_the_wrong_esp_idf_lane(self):
        self.assertRefused(["esp32c5", BOARD], "esp32c5 builds with ESP-IDF 5.5.5", idf="v5.3.5")
        self.assertRefused(["esp32s3", "n8r8"], "esp32s3 builds with ESP-IDF 5.3.5", idf="v5.5.5")

    def test_accepts_the_c5_baseline_on_its_lane(self):
        # Passes validation and reaches ESP-IDF (the fake then fails the build).
        code, _, configured = self.run_script("esp32c5", BOARD, "baseline", idf="v5.5.5")
        self.assertTrue(configured)
        self.assertNotEqual(code, 2)

    def test_s3_wrapper_keeps_the_s3_lane(self):
        wrapper = (ROOT / "ci/build-esp32s3.sh").read_text()
        self.assertIn('build-firmware.sh" esp32s3 "${1:-n8r8}" "${@:2}"', wrapper)


if __name__ == "__main__":
    unittest.main()
