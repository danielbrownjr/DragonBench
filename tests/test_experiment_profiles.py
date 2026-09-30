"""DragonBench images are one board profile plus one experiment profile.

Experiment profiles are a mutually exclusive Kconfig choice, never independently
combinable feature flags. Each non-baseline profile has exactly one overlay,
one name, one CI entry, and code compiled only under its DB_EXPERIMENT_* macro.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
KCONFIG = ROOT / "firmware/main/Kconfig.projbuild"
EXPERIMENT_H = ROOT / "firmware/common/include/db_experiment.h"
EXPECTED = {"DB_EXPERIMENT_BASELINE": "baseline",
            "DB_EXPERIMENT_FAN_CHARACTERIZATION": "fan-characterization"}
EXPERIMENT_OVERLAYS = sorted(f"sdkconfig.defaults.{n}" for n in EXPECTED.values() if n != "baseline")


BUILD_SCRIPT = ROOT / "ci/build-firmware.sh"


def _board_cases():
    """(SoC target, board) -> (SDKCONFIG_DEFAULTS layers, supported experiments).

    Parsed from the board case of ci/build-firmware.sh, the one place a board
    profile is defined. Raises ValueError if the case block cannot be found.
    """
    script = BUILD_SCRIPT.read_text()
    cases = script[script.index('case "$target/$board" in\n'):]
    cases = cases[:cases.index("\nesac\n")]
    found = re.findall(r'^    (\w+)/([\w-]+)\)\n        defaults="([^"$]+)"\n        experiments="([^"]*)"$',
                       cases, re.M)
    return {(target, board): (defaults.split(";"), experiments.split())
            for target, board, defaults, experiments in found}


def soc_targets():
    """SoC targets with at least one board profile, sorted."""
    return sorted({target for target, _ in _board_cases()})


def board_profiles(target="esp32s3"):
    """Board name -> SDKCONFIG_DEFAULTS layering for one SoC target.

    A board overlay is any file the layering names beyond the shared
    sdkconfig.defaults. The SoC target's sdkconfig.defaults.<target> is not
    listed: ESP-IDF adds it itself (see idf_layers).
    """
    return {board: layers for (t, board), (layers, _) in _board_cases().items() if t == target}


def board_experiments(target, board):
    """Experiment profiles ci/build-firmware.sh accepts for one board."""
    return _board_cases()[(target, board)][1]


def idf_layers(target, layers):
    """The files ESP-IDF actually applies, in order: after each SDKCONFIG_DEFAULTS
    entry it applies <entry>.<target> when that file exists."""
    applied = []
    for layer in layers:
        applied.append(layer)
        if (ROOT / f"{layer}.{target}").is_file():
            applied.append(f"{layer}.{target}")
    return applied


def board_overlays():
    """Every board overlay file named by any SoC target's board layering."""
    return sorted({f for target in soc_targets() for layers in board_profiles(target).values()
                   for f in layers if f != "sdkconfig.defaults"})


def target_overlays():
    """The sdkconfig.defaults.<soc> file of every SoC target with a board."""
    return sorted(f"sdkconfig.defaults.{target}" for target in soc_targets())


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

    def test_board_profiles_are_explicit(self):
        self.assertEqual(soc_targets(), ["esp32c5", "esp32s3"])
        self.assertEqual(sorted(board_profiles("esp32s3")), ["n16r8", "n8r8", "tinys3d"])
        self.assertEqual(sorted(board_profiles("esp32c5")), ["wroom1u-n32r8"])
        for target in soc_targets():
            for board, layers in board_profiles(target).items():
                # Every board layers on the shared defaults and names no
                # experiment and no SoC target file (ESP-IDF adds that itself).
                self.assertEqual(layers[0], "sdkconfig.defaults", board)
                self.assertFalse(set(layers) & set(EXPERIMENT_OVERLAYS), board)
                self.assertFalse(set(layers) & set(target_overlays()), board)
                self.assertIn(f"sdkconfig.defaults.{target}", idf_layers(target, layers), board)

    def test_soc_target_defaults_follow_the_shared_defaults(self):
        for target in soc_targets():
            self.assertEqual(idf_layers(target, ["sdkconfig.defaults"]),
                             ["sdkconfig.defaults", f"sdkconfig.defaults.{target}"])

    def test_every_defaults_overlay_is_a_board_an_experiment_or_a_soc_target(self):
        overlays = sorted(p.name for p in ROOT.glob("sdkconfig.defaults.*"))
        self.assertEqual(overlays, sorted(board_overlays() + EXPERIMENT_OVERLAYS + target_overlays()))
        self.assertIn("sdkconfig.defaults.n16r8", board_overlays())
        self.assertNotIn("sdkconfig.defaults.n16r8", EXPERIMENT_OVERLAYS)
        # A board overlay named like <x>.<target> would be applied by ESP-IDF
        # to every image whose layering contains <x>.
        for overlay in board_overlays() + EXPERIMENT_OVERLAYS:
            for target in soc_targets():
                self.assertFalse(overlay.endswith(f".{target}"), overlay)

    def test_baseline_is_explicit_and_boards_do_not_choose_experiments(self):
        self.assertIn("CONFIG_DB_EXPERIMENT_BASELINE=y", (ROOT / "sdkconfig.defaults").read_text())
        for overlay in board_overlays() + target_overlays():
            self.assertNotIn("DB_EXPERIMENT", (ROOT / overlay).read_text(), overlay)

    def test_soc_target_defaults_name_no_board(self):
        for overlay in target_overlays():
            self.assertNotIn("CONFIG_DB_TARGET_NAME", (ROOT / overlay).read_text(), overlay)

    def test_each_experiment_has_exactly_one_overlay_selecting_only_itself(self):
        for overlay in EXPERIMENT_OVERLAYS:
            self.assertTrue((ROOT / overlay).is_file(), overlay)
        for symbol, name in EXPECTED.items():
            if name == "baseline":
                continue
            settings = [l for l in (ROOT / f"sdkconfig.defaults.{name}").read_text().splitlines()
                        if l.startswith("CONFIG_DB_EXPERIMENT_")]
            self.assertEqual(settings, [f"CONFIG_{symbol}=y"], name)
            # An experiment overlay is not a board profile.
            self.assertNotIn("CONFIG_DB_TARGET_NAME", (ROOT / f"sdkconfig.defaults.{name}").read_text(), name)

    def test_ci_knows_every_experiment(self):
        script = BUILD_SCRIPT.read_text()
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
                # Every board that supports the experiment compiles its real backend.
                supporting = [board for target in soc_targets() for board in board_profiles(target)
                              if name in board_experiments(target, board)]
                self.assertEqual(sorted(re.findall(r"^          - board: ([\w-]+)$", job, re.M)),
                                 sorted(supporting), name)

    def test_every_board_has_a_hosted_baseline_build(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        job = workflow[workflow.index("\n  esp32s3-build:\n"):]
        job = job[:job.index("\n  esp32c5-build:\n")]
        self.assertIn("command: bash ci/build-esp32s3.sh ${{ matrix.profile }} baseline", job)
        profiles = re.search(r"^        profile: \[([^\]]*)\]$", job, re.M).group(1)
        self.assertEqual(sorted(p.strip() for p in profiles.split(",")), sorted(board_profiles("esp32s3")))

        job = workflow[workflow.index("\n  esp32c5-build:\n"):]
        job = job[:job.index("\n  fan-characterization-configured:\n")]
        self.assertIn("command: bash ci/build-firmware.sh esp32c5 ${{ matrix.profile }} baseline", job)
        profiles = re.search(r"^        profile: \[([^\]]*)\]$", job, re.M).group(1)
        self.assertEqual(sorted(p.strip() for p in profiles.split(",")), sorted(board_profiles("esp32c5")))

    def test_each_soc_target_builds_with_its_own_esp_idf(self):
        # The S3 lane stays on 5.3.5; ESP32-C5 needs 5.5.1+ and must never be
        # built by the S3 lane (or the reverse).
        script = BUILD_SCRIPT.read_text()
        lanes = dict(re.findall(r'^    (\w+)\)\n        idf_version="([\d.]+)"$', script, re.M))
        self.assertEqual(lanes, {"esp32s3": "5.3.5", "esp32c5": "5.5.5"})
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        jobs = re.split(r"^  (?=[\w-]+:\n)", workflow.split("\njobs:\n", 1)[1], flags=re.M)
        for job in filter(str.strip, jobs):
            targets = re.findall(r"^          target: (\w+)$", job, re.M)
            versions = re.findall(r"^          esp_idf_version: v([\d.]+)$", job, re.M)
            self.assertEqual(len(targets), len(versions), job.splitlines()[0])
            for target, version in zip(targets, versions):
                self.assertEqual(lanes[target], version, job.splitlines()[0])
        self.assertIn("target: esp32c5", workflow)

    def test_code_selects_experiments_only_through_db_experiment_h(self):
        for path in (ROOT / "firmware").rglob("*.[ch]"):
            if path == EXPERIMENT_H:
                continue
            self.assertNotIn("CONFIG_DB_EXPERIMENT_", path.read_text(), path)


if __name__ == "__main__":
    unittest.main()
