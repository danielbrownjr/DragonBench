"""Artifacts must say what produced them: build, board profile, experiment
profile, and device, plus a truthful source for every measured quantity."""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.dragonbench.main import execute, parser

ROOT = Path(__file__).parents[1]
MAIN_C = ROOT / "firmware/targets/esp32s3/main/main.c"
PROVENANCE_CMAKE = ROOT / "firmware/targets/esp32s3/main/build_provenance.cmake"


def _function_body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


class IdentityTests(unittest.TestCase):
    def test_device_identity_names_build_board_experiment_and_device(self):
        identity = _function_body(MAIN_C.read_text(), "static cJSON *identity_json")
        self.assertIn('"board_profile", CONFIG_DB_TARGET_NAME', identity)
        self.assertIn('"experiment_profile", DB_EXPERIMENT_PROFILE_NAME', identity)
        self.assertIn('"device_id", device_id', identity)
        self.assertIn("add_build(o);", identity)
        build = _function_body(MAIN_C.read_text(), "static void add_build")
        self.assertIn('cJSON_AddNullToObject(b, "git_sha")', build)
        self.assertIn('"source_tree", DB_BUILD_SOURCE_TREE', build)

    def test_boot_event_carries_image_identity(self):
        source = MAIN_C.read_text()
        boot = source[source.index("char image[192];"):source.index('emit_event("boot"')]
        for field in ("board_profile", "experiment_profile", "git_sha", "source_tree"):
            self.assertIn(field, boot)
        self.assertIn('emit_event("boot", NULL, prior_run, NULL, image, NULL);', source)

    def test_provenance_header_is_regenerated_every_build(self):
        cmake = (ROOT / "firmware/targets/esp32s3/main/CMakeLists.txt").read_text()
        self.assertIn("add_custom_target(db_build_provenance", cmake)
        self.assertIn("add_dependencies(${COMPONENT_LIB} db_build_provenance)", cmake)
        self.assertIn('#include "db_build_provenance.h"', MAIN_C.read_text())

    def test_host_artifacts_include_device_identity(self):
        class Fake:
            def __init__(self): self.paths = []
            def request(self, method, path, body=None):
                self.paths.append(path)
                if path == "/api/v1/device": return {"experiment_profile": "baseline"}
                if path == "/api/v1/events": return []
                return {"run_id": "r"}
        fake = Fake()
        exported = execute(parser().parse_args(["export", "r"]), fake)
        self.assertEqual(exported["device"], {"experiment_profile": "baseline"})


@unittest.skipUnless(shutil.which("cmake") and shutil.which("git"), "needs cmake and git")
class BuildProvenanceScriptTests(unittest.TestCase):
    def run_script(self, source_dir, output):
        subprocess.run(["cmake", f"-DSOURCE_DIR={source_dir}", f"-DOUTPUT={output}", "-P", str(PROVENANCE_CMAKE)],
                       check=True, capture_output=True)
        text = output.read_text()
        sha = re.search(r'#define DB_BUILD_GIT_SHA "([^"]*)"', text).group(1)
        tree = re.search(r'#define DB_BUILD_SOURCE_TREE "([^"]*)"', text).group(1)
        return sha, tree

    def test_reports_clean_dirty_and_unknown_truthfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, header = Path(tmp) / "repo", Path(tmp) / "provenance.h"
            repo.mkdir()
            git = ["git", "-C", str(repo), "-c", "user.email=bench@example.invalid", "-c", "user.name=bench"]
            subprocess.run(git + ["init", "-q"], check=True)
            (repo / "f.c").write_text("int x;\n")
            subprocess.run(git + ["add", "f.c"], check=True)
            subprocess.run(git + ["commit", "-qm", "init"], check=True)
            head = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

            self.assertEqual(self.run_script(repo, header), (head, "clean"))
            before = header.stat().st_mtime_ns
            self.assertEqual(self.run_script(repo, header), (head, "clean"))
            self.assertEqual(header.stat().st_mtime_ns, before, "unchanged provenance must not rewrite the header")

            (repo / "f.c").write_text("int y;\n")
            self.assertEqual(self.run_script(repo, header), (head, "dirty"))
            (repo / "f.c").write_text("int x;\n")
            (repo / "new.c").write_text("int z;\n")
            self.assertEqual(self.run_script(repo, header), (head, "dirty"))

            plain = Path(tmp) / "not-a-repo"
            plain.mkdir()
            self.assertEqual(self.run_script(plain, header), ("", "unknown"))


class MeasurementProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.body = _function_body(MAIN_C.read_text(), "static void add_measurement_provenance")
        self.pairs = re.findall(r'cJSON_AddStringToObject\(m, "(\w+)",\s*"([^"]+)"\)', self.body)

    def test_measurement_authority_claim_is_gone(self):
        for path in (MAIN_C, ROOT / "web/index.html", ROOT / "protocol/openapi.yaml"):
            self.assertNotIn("measurement_authority", path.read_text(), path)

    def test_every_source_is_dut_derived_or_external(self):
        for quantity, source in self.pairs:
            self.assertRegex(source, r"^(external|dut\.esp32s3_\w+|derived\.\w+)$", quantity)
        self.assertIn('"fan_speed",\n                            fan_characterization_ppr() ? '
                      '"derived.fan_tach_edges_and_configured_ppr" : "external"', self.body)

    def test_dut_claims_match_what_firmware_acquires(self):
        sources = dict(self.pairs)
        self.assertEqual(sources["soc_temperature"], "dut.esp32s3_temperature_sensor")
        self.assertEqual(sources["wifi_rssi"], "dut.esp32s3_wifi")
        self.assertEqual(sources["fan_tach_edges"], "dut.esp32s3_pcnt")
        for external in ("supply_voltage", "supply_current", "rail_voltage", "reset_and_brownout",
                         "fan_airflow", "fan_temperature", "fan_supply_current", "fan_supply_voltage",
                         "fan_pwm_line_waveform"):
            self.assertEqual(sources[external], "external", external)
        # The on-board supply sensors really are absent.
        self.assertIn('"supply_voltage", "MCU supply voltage", "V", "none", "unsupported"', MAIN_C.read_text())

    def test_fan_quantities_exist_only_in_the_fan_profile(self):
        guard = self.body.index("#if DB_EXPERIMENT_FAN_CHARACTERIZATION")
        end = self.body.index("#endif", guard)
        for match in re.finditer(r'"(fan_\w+)"', self.body):
            self.assertTrue(guard < match.start() < end, match.group(1))


if __name__ == "__main__":
    unittest.main()
