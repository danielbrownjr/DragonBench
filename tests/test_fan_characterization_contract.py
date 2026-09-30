"""Static contract for the fan-characterization experiment profile.

The profile is characterization equipment: an external open-drain PWM stimulus
and tach capture, compiled only when this experiment profile is selected. These
checks keep it out of every other profile, keep it from growing product fan
control, and keep guessed wiring or fan constants out of it. The profile
mechanism itself is covered by test_experiment_profiles.py.
"""

import re
import unittest
from pathlib import Path

from cli.dragonbench import main as cli

ROOT = Path(__file__).parents[1]
MAIN_C = ROOT / "firmware/main/main.c"
FIXTURE_C = ROOT / "firmware/main/fan_characterization.c"
DB_FAN_H = ROOT / "firmware/common/include/db_fan.h"
KCONFIG = ROOT / "firmware/main/Kconfig.projbuild"


def _read(path):
    return (path if isinstance(path, Path) else ROOT / path).read_text()


def _kconfig_default(name):
    match = re.search(rf"config {name}\n(?:.*\n)*?\s+default (\S+)", _read(KCONFIG))
    return match.group(1)


def _function_body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


class ProfileIsolationTests(unittest.TestCase):
    def test_fixture_wiring_has_no_defaults(self):
        self.assertEqual(_kconfig_default("DB_FAN_PWM_GATE_GPIO"), "-1")
        self.assertEqual(_kconfig_default("DB_FAN_GATE_SINK_LEVEL"), "-1")
        self.assertEqual(_kconfig_default("DB_FAN_TACH_GPIO"), "-1")
        self.assertEqual(_kconfig_default("DB_FAN_TACH_PPR"), "0")
        self.assertEqual(_kconfig_default("DB_FAN_TACH_INTERNAL_PULLUP"), "n")
        self.assertEqual(_kconfig_default("DB_FAN_TACH_PPR_EVIDENCE"), '""')

    def test_fixture_wiring_exists_only_inside_the_profile(self):
        kconfig = _read(KCONFIG)
        block = kconfig[kconfig.index("if DB_EXPERIMENT_FAN_CHARACTERIZATION\n"):]
        block = block[:block.index("\nendif\n")]
        self.assertEqual(kconfig.count("config DB_FAN_"), block.count("config DB_FAN_"))
        for board in ("sdkconfig.defaults", "sdkconfig.defaults.n16r8", "sdkconfig.defaults.tinys3d"):
            self.assertNotIn("DB_FAN", _read(board), board)

    def test_overlay_only_selects_the_profile_and_assigns_no_pins(self):
        overlay = _read("sdkconfig.defaults.fan-characterization")
        settings = [line for line in overlay.splitlines() if line and not line.startswith("#")]
        self.assertEqual(settings, ["CONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION=y"])
        self.assertIn("# CONFIG_DB_EXPERIMENT_BASELINE is not set", overlay)
        self.assertIn("sdkconfig.fan-characterization.local", _read(".gitignore"))

    def test_unconfigured_profile_refuses_to_build(self):
        source = _read(FIXTURE_C)
        for setting in ("CONFIG_DB_FAN_PWM_GATE_GPIO", "CONFIG_DB_FAN_GATE_SINK_LEVEL", "CONFIG_DB_FAN_TACH_GPIO"):
            self.assertRegex(source, rf"#if {setting} < 0\n#error \"fan-characterization: set {setting}")
        self.assertIn("DB_FAN_PIN_RESERVED(CONFIG_DB_FAN_PWM_GATE_GPIO", source)
        self.assertIn("DB_FAN_PIN_RESERVED(CONFIG_DB_FAN_TACH_GPIO", source)
        self.assertIn("CONFIG_DB_RF_SWITCH_GPIO", source)
        self.assertIn("CONFIG_DB_STATUS_RGB_GPIO", source)
        self.assertIn("CONFIG_DB_STATUS_RGB_POWER_GPIO", source)
        self.assertIn("CONFIG_DB_FAN_TACH_PPR_EVIDENCE", source)

    def test_profile_code_is_compiled_out_of_other_profiles(self):
        fixture = _read(FIXTURE_C)
        self.assertLess(fixture.index("#if DB_EXPERIMENT_FAN_CHARACTERIZATION"), fixture.index("driver/ledc.h"))
        main = _read(MAIN_C)
        for call in ("fan_characterization_boot()", "fan_characterization_hold(", "fan_characterization_describe("):
            idx = main.index(call)
            # Inside an open "#if DB_EXPERIMENT_FAN_CHARACTERIZATION" block.
            self.assertGreater(main.rfind("#if DB_EXPERIMENT_FAN_CHARACTERIZATION", 0, idx),
                               main.rfind("#endif", 0, idx), call)
        self.assertIn("return DB_EXPERIMENT_FAN_CHARACTERIZATION;", _read("firmware/common/db_run.c"))

    def test_ci_proves_absence_and_refusal(self):
        script = _read("ci/build-firmware.sh")
        self.assertIn('[fan-characterization]="ledc_|pcnt_|fan_characterization_"', script)
        self.assertIn("links $other code", script)
        workflow = _read(".github/workflows/ci.yml")
        self.assertIn("ci/build-esp32s3.sh tinys3d fan-characterization --expect-refusal", workflow)
        self.assertIn("-DCONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION=1", workflow)


class ProductBoundaryTests(unittest.TestCase):
    def test_product_actuator_capabilities_are_false_in_every_build(self):
        main = _read(MAIN_C)
        identity = _function_body(main, "static cJSON *identity_json")
        heater = identity.index('"heater_capability", false')
        fan = identity.index('"fan_control_capability", false')
        guard = identity.index("#if DB_EXPERIMENT_FAN_CHARACTERIZATION")
        self.assertLess(heater, guard)
        self.assertLess(fan, guard)
        self.assertIn('"fan_pwm_fixture", DB_EXPERIMENT_FAN_CHARACTERIZATION', identity)

    def test_no_heater_path_anywhere_in_firmware(self):
        # "heater" may appear only where the absent capability is reported.
        allowed = ("capability", "no heater")
        for path in (ROOT / "firmware").rglob("*"):
            if path.suffix not in (".c", ".h", ".projbuild", ".txt"):
                continue
            for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                lowered = line.lower()
                if "heater" in lowered:
                    self.assertTrue(any(token in lowered for token in allowed), f"{path}:{number}: {line}")

    def test_tach_never_feeds_the_stimulus(self):
        source = _read(FIXTURE_C)
        for helper in ("ledc_timer_config", "ledc_channel_config", "ledc_set_duty", "ledc_update_duty",
                       "ledc_set_freq", "ledc_set_fade"):
            for match in re.finditer(rf"\b{helper}\(", source):
                enclosing = source.rindex("\nstatic ", 0, match.start())
                self.assertTrue(source.startswith("\nstatic bool start_pwm", enclosing), helper)
        common = _read("firmware/common/db_fan.c")
        hold = _function_body(common, "db_fan_hold_outcome_t db_fan_hold(")
        self.assertEqual(hold.count("actuate("), 1)
        self.assertLess(hold.index("actuate("), hold.index("ops->tach_read("))
        self.assertNotIn("tach", _function_body(common, "static bool actuate("))

    def test_release_is_first_in_boot_and_on_every_hold_exit(self):
        main = _read(MAIN_C)
        app_main = main[main.index("void app_main(void) {"):]
        first_statement = app_main.split("\n")[2].strip()
        self.assertEqual(first_statement, "fan_characterization_boot(); // release the stimulus line before anything else")
        common = _read("firmware/common/db_fan.c")
        hold = _function_body(common, "db_fan_hold_outcome_t db_fan_hold(")
        tail = hold[hold.index("\nrelease:"):]
        self.assertIn("db_fan_release(fixture)", tail)
        self.assertNotIn("return", hold[hold.index("actuate("):hold.index("\nrelease:")])
        self.assertIn("return fixture->gate_sink_level ? 0 : 1;", common)
        fixture = _read(FIXTURE_C)
        self.assertIn("esp_register_shutdown_handler(shutdown_release)", fixture)
        drive = _function_body(fixture, "static bool drive_static")
        self.assertLess(drive.index("gpio_set_level(GATE_GPIO, gate_level)"), drive.index("gpio_config("))
        self.assertIn("GPIO_PULLUP_DISABLE", drive)
        self.assertIn("GPIO_PULLDOWN_DISABLE", drive)

    def test_tach_readiness_is_established_before_actuation(self):
        hold = _function_body(_read("firmware/common/db_fan.c"), "db_fan_hold_outcome_t db_fan_hold(")
        ready = hold.index("ops->tach_ready(")
        self.assertLess(hold.index("db_fan_release(fixture)"), ready)
        self.assertLess(ready, hold.index("actuate("))
        # The counter is cleared after actuation, immediately before the window opens.
        clear = hold.index("ops->tach_clear(")
        self.assertLess(hold.index("actuate("), clear)
        self.assertLess(clear, hold.index("result->window_start_us = ops->now_us("))

    def test_static_endpoints_never_use_ledc(self):
        plan = _function_body(_read("firmware/common/db_fan.c"), "bool db_fan_stimulus_plan(")
        self.assertLess(plan.index("DB_FAN_STIMULUS_STATIC_RELEASE"), plan.index("DB_FAN_STIMULUS_PWM"))
        self.assertLess(plan.index("DB_FAN_STIMULUS_STATIC_SINK"), plan.index("DB_FAN_STIMULUS_PWM"))
        self.assertIn("counts >= full_scale", plan)
        start_pwm = _function_body(_read(FIXTURE_C), "static bool start_pwm(")
        self.assertIn("duty_counts >= (1UL << resolution_bits)", start_pwm)

    def test_no_jumpjet_policy_constants(self):
        sources = list((ROOT / "firmware").rglob("*.[ch]")) + [KCONFIG]
        text = "\n".join(p.read_text(errors="ignore") for p in sources).upper()
        policy = re.compile(r"\b\w*(MIN_DUTY|MINIMUM_DUTY|STALL_|_STALL|PROOF|RPM_MIN|MIN_RPM|RPM_THRESHOLD|"
                            r"FAN_TIMEOUT|FAN_PWM_HZ_DEFAULT|DEFAULT_PPR)\w*\b")
        self.assertEqual(policy.findall(text), [])


class ContractSyncTests(unittest.TestCase):
    def test_cli_limits_mirror_firmware(self):
        header = _read(DB_FAN_H)
        self.assertIn(f"#define DB_FAN_PWM_HZ_MIN {cli.FAN_PWM_HZ_MIN}U", header)
        self.assertIn(f"#define DB_FAN_PWM_HZ_MAX {cli.FAN_PWM_HZ_MAX}U", header)
        api = _read("protocol/openapi.yaml")
        self.assertIn(f"pwm_hz: {{type: integer, minimum: {cli.FAN_PWM_HZ_MIN}, maximum: {cli.FAN_PWM_HZ_MAX}", api)
        self.assertIn("sink_duty_pct: {type: number, minimum: 0, maximum: 100, multipleOf: 0.1", api)
        self.assertIn("FAN_PWM_HOLD", api)
        self.assertIn("bench_stimulus", api)

    def test_landing_pages_show_the_stimulus_separately_from_product_control(self):
        from tests.test_contract import _firmware_page
        for page in (_read("web/index.html"), _firmware_page("landing")):
            self.assertIn('data-role="capability-fan-stimulus"', page)
            self.assertIn("bench_stimulus", page)
            self.assertNotIn("cannot drive a heater or fan", page)
            self.assertIn("no heater or product fan-control path", page)

    def test_unknown_ppr_stays_explicit(self):
        common = _read("firmware/common/db_fan.c")
        self.assertIn('",\\"ppr\\":%s,\\"rpm\\":null", ppr ? "\\"invalid\\"" : "null"', common)
        self.assertIn('cJSON_AddNullToObject(o, "tach_ppr")', _read(FIXTURE_C))


if __name__ == "__main__":
    unittest.main()
