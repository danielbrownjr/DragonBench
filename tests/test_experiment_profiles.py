"""DragonBench images are one board profile plus one experiment profile.

Experiment profiles are a mutually exclusive Kconfig choice, never independently
combinable feature flags. Each non-baseline profile has exactly one overlay,
one name, one CI entry, and code compiled only under its DB_EXPERIMENT_* macro.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
KCONFIG = ROOT / "firmware/targets/esp32s3/main/Kconfig.projbuild"
EXPERIMENT_H = ROOT / "firmware/common/include/db_experiment.h"
EXPECTED = {"DB_EXPERIMENT_BASELINE": "baseline",
            "DB_EXPERIMENT_FAN_CHARACTERIZATION": "fan-characterization"}


def _choice_block():
    kconfig = KCONFIG.read_text()
    start = kconfig.index("choice DB_EXPERIMENT_PROFILE\n")
    return kconfig[start:kconfig.index("endchoice", start)]


class ExperimentProfileTests(unittest.TestCase):
    def test_profiles_are_one_mutually_exclusive_choice(self):
        block = _choice_block()
        self.assertIn("default DB_EXPERIMENT_BASELINE", block)
        self.assertEqual(sorted(re.findall(r"^config (DB_EXPERIMENT_\w+)$", block, re.M)), sorted(EXPECTED))
        # No experiment switch lives outside the choice.
        kconfig = KCONFIG.read_text()
        outside = kconfig.replace(block, "")
        self.assertEqual(re.findall(r"^config (DB_EXPERIMENT_\w+)$", outside, re.M), [])
        self.assertNotIn("config DB_FAN_FIXTURE", kconfig)

    def test_every_profile_has_one_name(self):
        header = EXPERIMENT_H.read_text()
        for symbol, name in EXPECTED.items():
            self.assertIn(f'#define DB_EXPERIMENT_PROFILE_NAME "{name}"', header, symbol)
        self.assertEqual(header.count("#define DB_EXPERIMENT_PROFILE_NAME"), len(EXPECTED))

    def test_baseline_is_explicit_and_boards_do_not_choose_experiments(self):
        self.assertIn("CONFIG_DB_EXPERIMENT_BASELINE=y", (ROOT / "sdkconfig.defaults").read_text())
        self.assertNotIn("DB_EXPERIMENT", (ROOT / "sdkconfig.defaults.tinys3d").read_text())

    def test_each_experiment_has_exactly_one_overlay_selecting_only_itself(self):
        overlays = sorted(p.name for p in ROOT.glob("sdkconfig.defaults.*") if p.name != "sdkconfig.defaults.tinys3d")
        experiments = sorted(n for n in EXPECTED.values() if n != "baseline")
        self.assertEqual(overlays, [f"sdkconfig.defaults.{n}" for n in experiments])
        for symbol, name in EXPECTED.items():
            if name == "baseline":
                continue
            settings = [l for l in (ROOT / f"sdkconfig.defaults.{name}").read_text().splitlines()
                        if l.startswith("CONFIG_DB_EXPERIMENT_")]
            self.assertEqual(settings, [f"CONFIG_{symbol}=y"], name)

    def test_ci_knows_every_experiment(self):
        script = (ROOT / "ci/build-esp32s3.sh").read_text()
        listed = re.search(r"^all_experiments=\(([^)]*)\)", script, re.M).group(1).split()
        self.assertEqual(sorted(listed), sorted(n for n in EXPECTED.values() if n != "baseline"))

    def test_every_experiment_has_a_configured_hosted_build(self):
        # Refusal and static checks are not enough: hosted CI must compile each
        # non-baseline experiment's real backend, with runner-local wiring.
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        jobs = re.split(r"^  (?=[\w-]+:\n)", workflow.split("\njobs:\n", 1)[1], flags=re.M)
        for name in (n for n in EXPECTED.values() if n != "baseline"):
            configured = [job for job in jobs
                          if re.search(rf"command: bash ci/build-esp32s3\.sh .+ {re.escape(name)}[ \t]*$", job, re.M)]
            self.assertTrue(configured, f"{name} has no configured ESP-IDF CI build")
            for job in configured:
                self.assertIn(f"cat > sdkconfig.{name}.local", job, name)
                self.assertIn("CI COMPILE FIXTURE", job, name)

    def test_code_selects_experiments_only_through_db_experiment_h(self):
        for path in (ROOT / "firmware").rglob("*.[ch]"):
            if path == EXPERIMENT_H:
                continue
            self.assertNotIn("CONFIG_DB_EXPERIMENT_", path.read_text(), path)


if __name__ == "__main__":
    unittest.main()
