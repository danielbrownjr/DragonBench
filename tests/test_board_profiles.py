"""Board profiles: what each sdkconfig.defaults[.<board>] layering configures.

A board profile states the module's flash, PSRAM line mode, reported identity,
and board-owned GPIOs. It never selects an experiment (test_experiment_profiles.py).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# A module import, so this file does not re-collect ExperimentProfileTests.
import test_experiment_profiles as profiles

ROOT = Path(__file__).parents[1]
KCONFIG = ROOT / "firmware/main/Kconfig.projbuild"
FIXTURE_C = ROOT / "firmware/main/fan_characterization.c"

EXPECTED = {
    # board: (CONFIG_DB_TARGET_NAME, flash size, PSRAM mode, RF-switch GPIO,
    #         status RGB data GPIO, status RGB power GPIO)
    "n8r8": ("esp32s3-n8r8", "8MB", "OCT", -1, 48, -1),
    "n16r8": ("esp32s3-n16r8", "16MB", "OCT", -1, 48, -1),
    "tinys3d": ("esp32s3-tinys3d", "8MB", "QUAD", 38, 18, 17),
}
GPIO_SETTINGS = ("DB_RF_SWITCH_GPIO", "DB_STATUS_RGB_GPIO", "DB_STATUS_RGB_POWER_GPIO",
                 "DB_STATUS_RGB_POWER_ACTIVE_LEVEL")


def _kconfig_int_default(name):
    return int(re.search(rf"config {name}\n(?:.*\n)*?\s+default (-?\d+)", KCONFIG.read_text()).group(1))


def resolved(board, target="esp32s3"):
    """Settings after layering the board's defaults files in order, as ESP-IDF
    does, including the SoC target's sdkconfig.defaults.<target>. Kconfig
    defaults are filled in only for the board-owned GPIO settings."""
    settings = {}
    for layer in profiles.idf_layers(target, profiles.board_profiles(target)[board]):
        for line in (ROOT / layer).read_text().splitlines():
            unset = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
            if unset:
                settings.pop(unset.group(1), None)
            elif line.startswith("CONFIG_"):
                key, value = line.split("=", 1)
                settings[key] = value
    for name in GPIO_SETTINGS:
        settings.setdefault(f"CONFIG_{name}", str(_kconfig_int_default(name)))
    return settings


def _selected(settings, prefix, options):
    chosen = [o for o in options if settings.get(f"{prefix}{o}") == "y"]
    return chosen[0] if len(chosen) == 1 else chosen


class BoardProfileTests(unittest.TestCase):
    def test_every_board_is_described(self):
        self.assertEqual(sorted(profiles.board_profiles()), sorted(EXPECTED))

    def test_board_configuration(self):
        for board, (target, flash, psram, rf_switch, rgb, rgb_power) in EXPECTED.items():
            with self.subTest(board=board):
                settings = resolved(board)
                self.assertEqual(settings.get("CONFIG_DB_TARGET_NAME", '"esp32s3-n8r8"'), f'"{target}"')
                self.assertEqual(_selected(settings, "CONFIG_ESPTOOLPY_FLASHSIZE_",
                                           ("2MB", "4MB", "8MB", "16MB", "32MB")), flash)
                self.assertEqual(settings.get("CONFIG_SPIRAM"), "y")
                self.assertEqual(_selected(settings, "CONFIG_SPIRAM_MODE_", ("QUAD", "OCT")), psram)
                self.assertEqual(int(settings["CONFIG_DB_RF_SWITCH_GPIO"]), rf_switch)
                self.assertEqual(int(settings["CONFIG_DB_STATUS_RGB_GPIO"]), rgb)
                self.assertEqual(int(settings["CONFIG_DB_STATUS_RGB_POWER_GPIO"]), rgb_power)
                # TinyS3[D] schematic Rev D-P1: GPIO17 high powers the LED.
                self.assertEqual(int(settings["CONFIG_DB_STATUS_RGB_POWER_ACTIVE_LEVEL"]), 1)

    def test_n16r8_is_octal_psram_at_80_mhz(self):
        settings = resolved("n16r8")
        self.assertEqual(settings.get("CONFIG_SPIRAM_SPEED_80M"), "y")
        self.assertEqual(settings.get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME"), '"partitions.csv"')

    def test_n8r8_remains_the_default_board(self):
        default = re.search(r'config DB_TARGET_NAME\n(?:.*\n)*?\s+default "([^"]+)"', KCONFIG.read_text()).group(1)
        self.assertEqual(default, "esp32s3-n8r8")
        self.assertEqual(profiles.board_profiles()["n8r8"], ["sdkconfig.defaults"])
        self.assertEqual(resolved("n8r8").get("CONFIG_IDF_TARGET"), '"esp32s3"')

    def test_every_board_identity_is_a_protocol_target(self):
        schema = json.loads((ROOT / "protocol/event.schema.json").read_text())
        targets = schema["properties"]["target"]["enum"]
        openapi = re.search(r"board_profile: \{type: string, enum: \[([^\]]*)\]\}",
                            (ROOT / "protocol/openapi.yaml").read_text()).group(1)
        expected = sorted([target for target, *_ in EXPECTED.values()] + ["esp32c5-wroom1u-n32r8"])
        self.assertEqual(sorted(targets), expected)
        self.assertEqual(sorted(t.strip() for t in openapi.split(",")), expected)
        self.assertEqual(len(targets), len(set(targets)))

    def test_partition_layout_stays_below_8_mb_on_every_board(self):
        # The N16R8 has 16 MB of physical flash; the layout deliberately uses
        # only the lower 8 MB so one partitions.csv serves every board.
        end = 0
        for line in (ROOT / "partitions.csv").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            fields = [f.strip() for f in line.split(",")]
            end = max(end, int(fields[3], 0) + int(fields[4], 0))
        self.assertGreater(end, 0)
        self.assertLessEqual(end, 8 * 1024 * 1024)


@unittest.skipUnless(shutil.which("cc") or os.environ.get("DRAGONBENCH_REQUIRE_CC"),
                     "a C compiler is required to preprocess the fixture pin guards")
class FixturePinGuardTests(unittest.TestCase):
    """Runs the real fan-characterization pin guards through the C preprocessor
    with each board's resolved configuration."""

    @classmethod
    def setUpClass(cls):
        source = FIXTURE_C.read_text()
        start = source.index("#if CONFIG_DB_FAN_PWM_GATE_GPIO < 0\n")
        guards = source[start:source.index("// RPM is derived", start)]
        cls.tmp = tempfile.TemporaryDirectory()
        cls.guards = Path(cls.tmp.name) / "guards.c"
        # Close the "all fixture settings set" block the excerpt opens.
        cls.guards.write_text('#include "db_fan.h"\n' + guards + "#endif\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _errors(self, board, gate, tach, sink=1):
        settings = resolved(board)
        defines = [f"-DCONFIG_DB_FAN_PWM_GATE_GPIO={gate}", f"-DCONFIG_DB_FAN_TACH_GPIO={tach}",
                   f"-DCONFIG_DB_FAN_GATE_SINK_LEVEL={sink}"]
        defines += [f"-DCONFIG_{name}={settings[f'CONFIG_{name}']}" for name in GPIO_SETTINGS]
        if settings.get("CONFIG_SPIRAM_MODE_OCT") == "y":
            defines.append("-DCONFIG_SPIRAM_MODE_OCT=1")
        result = subprocess.run(["cc", "-E", "-o", os.devnull, *defines,
                                 f"-I{ROOT / 'firmware/common/include'}", str(self.guards)],
                                capture_output=True, text=True)
        errors = re.findall(r'#error "fan-characterization: ([^"]+)"', result.stderr)
        self.assertEqual(result.returncode != 0, bool(errors), result.stderr)
        return errors

    def assertAccepted(self, board, gate, tach, sink=1):
        self.assertEqual(self._errors(board, gate, tach, sink), [], f"{board} gate={gate} tach={tach}")

    def assertRejected(self, board, gate, tach, reason):
        errors = self._errors(board, gate, tach)
        self.assertTrue(any(reason in e for e in errors), f"{board} gate={gate} tach={tach}: {errors}")

    def test_hosted_ci_fixtures_pass_their_board_guards(self):
        self.assertAccepted("n16r8", 6, 7, sink=1)
        self.assertAccepted("n8r8", 6, 7, sink=0)
        self.assertAccepted("tinys3d", 4, 5, sink=1)

    def test_status_rgb_data_pin_is_rejected_as_gate_and_tach(self):
        for board in ("n8r8", "n16r8"):
            self.assertRejected(board, 48, 7, "CONFIG_DB_STATUS_RGB_GPIO")
            self.assertRejected(board, 6, 48, "CONFIG_DB_STATUS_RGB_GPIO")
        self.assertRejected("tinys3d", 18, 5, "CONFIG_DB_STATUS_RGB_GPIO")
        self.assertRejected("tinys3d", 4, 18, "CONFIG_DB_STATUS_RGB_GPIO")

    def test_status_rgb_power_pin_is_rejected_as_gate_and_tach(self):
        self.assertRejected("tinys3d", 17, 5, "CONFIG_DB_STATUS_RGB_POWER_GPIO")
        self.assertRejected("tinys3d", 4, 17, "CONFIG_DB_STATUS_RGB_POWER_GPIO")

    def test_status_rgb_pins_are_reserved_only_on_the_board_that_wires_them(self):
        self.assertAccepted("tinys3d", 48, 5)
        for board in ("n8r8", "n16r8"):
            self.assertAccepted(board, 17, 18)
            self.assertAccepted(board, 18, 17)

    def test_tinys3d_still_rejects_its_rf_switch(self):
        self.assertRejected("tinys3d", 38, 5, "CONFIG_DB_RF_SWITCH_GPIO")
        self.assertRejected("tinys3d", 4, 38, "CONFIG_DB_RF_SWITCH_GPIO")

    def test_octal_psram_pins_are_rejected_on_octal_boards_only(self):
        for board in ("n8r8", "n16r8"):
            for gpio in range(33, 38):
                self.assertRejected(board, gpio, 7, "flash/PSRAM")
        self.assertAccepted("tinys3d", 33, 5)

    def test_shared_reservations_hold_on_every_board(self):
        for board in EXPECTED:
            for gpio in (0, 3, 45, 46, 19, 20, 26, 43, 44, 49):
                self.assertRejected(board, gpio, 7 if board != "tinys3d" else 5, "strapping")
            self.assertRejected(board, 6, 6, "different GPIOs")


if __name__ == "__main__":
    unittest.main()
