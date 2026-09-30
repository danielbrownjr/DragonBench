import importlib.util
import unittest
from pathlib import Path

SEXP = Path(__file__).resolve().parents[1] / "hardware/fan-characterization-fixture/generator/sexp.py"
_spec = importlib.util.spec_from_file_location("fixture_sexp", SEXP)
sexp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sexp)


class StringEscapeTests(unittest.TestCase):
    """parse() must decode exactly the escapes q() writes, so library text survives parse -> dump."""

    CASES = {
        "plain": "Resistor",
        "quote": 'say "hi"',
        "backslash": "C:\\path",
        "newline": "line one\nline two",
        "escaped backslash before n": "\\n",
        "all together": 'a\\b "c"\nd',
    }

    def test_quoted_strings_round_trip(self):
        for name, text in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(sexp.parse(sexp.q(text)), [text])

    def test_parse_then_dump_is_unchanged(self):
        for name, text in self.CASES.items():
            with self.subTest(name):
                source = "(property " + sexp.q(text) + ")"
                self.assertEqual(sexp.dump(sexp.parse(source)[0]), source)

    def test_newline_escape_decodes_to_a_newline(self):
        self.assertEqual(sexp.parse(r'"a\nb"'), ["a\nb"])

    def test_unknown_escape_is_kept_as_written(self):
        self.assertEqual(sexp.parse(r'"a\xb"'), ["a\\xb"])


if __name__ == "__main__":
    unittest.main()
