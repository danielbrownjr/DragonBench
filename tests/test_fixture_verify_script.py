import re
import unittest
from pathlib import Path

VERIFY = (Path(__file__).resolve().parents[1] / "hardware/fan-characterization-fixture/verify.sh").read_text()


class VerifyScriptTests(unittest.TestCase):
    """verify.sh needs Docker and KiCad, so CI checks its structure; the behaviour is run by hand."""

    def test_update_copies_into_the_fixture_only_after_every_check(self):
        copies = [m.start() for m in re.finditer(r"\bcp [^\n]*/fixture/", VERIFY)]
        self.assertEqual(len(copies), 1, "one copy-back, at the end")
        for step in ("kicad-cli sch erc", "ERC messages: 0  Errors 0  Warnings 0",
                     "check_netlist.py", "kicad-cli sch export pdf", "kicad-cli sch export svg"):
            self.assertLess(VERIFY.index(step), copies[0], step)

    def test_checks_run_on_the_generated_schematic(self):
        self.assertLess(VERIFY.index("cd /out/gen"), VERIFY.index("kicad-cli sch erc"))

    def test_fixture_is_read_only_in_check_mode_and_output_stays_private(self):
        self.assertIn('FIXTURE_MOUNT="$HERE:/fixture:ro"', VERIFY)
        self.assertIn('[ "$MODE" = update ] && FIXTURE_MOUNT="$HERE:/fixture"', VERIFY)
        self.assertNotIn("chmod 777", VERIFY)
        self.assertIn("--network none", VERIFY)


if __name__ == "__main__":
    unittest.main()
