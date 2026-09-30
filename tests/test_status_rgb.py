"""The board status RGB LED: board-owned, green only when ready and idle.

The LED is load on the module supply, so it is off before any run's
measurement window opens and stays off until that run ends. The on/off policy
itself (db_status_ready) is exercised natively in tests/native/test_db_run.c;
these checks pin down where the firmware applies it and what the driver may do.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN_C = ROOT / "firmware/main/main.c"
DRIVER_C = ROOT / "firmware/main/status_rgb.c"
KCONFIG = ROOT / "firmware/main/Kconfig.projbuild"


def _function_body(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


def _locked_sections(body):
    """Each state_lock critical section in body, in order."""
    return re.findall(r"xSemaphoreTake\(state_lock, portMAX_DELAY\);(.*?)xSemaphoreGive\(state_lock\);", body, re.S)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.main = MAIN_C.read_text()

    def test_led_is_driven_only_from_the_state_sync(self):
        # One place turns the LED on or off, and it follows db_status_ready.
        self.assertEqual(self.main.count("status_rgb_set("), 1)
        sync = _function_body(self.main, "static void status_sync_locked(void)")
        self.assertIn("db_status_ready(device_ready, &current_run)", sync)
        self.assertIn("status_rgb_set(green)", sync)
        for workload in ("static bool run_cpu", "static bool run_network", "static bool run_nvs",
                         "static bool partition_cycle", "static bool wait_abortable"):
            self.assertNotIn("status_", _function_body(self.main, workload), workload)
        self.assertNotIn("status_", (ROOT / "firmware/main/fan_characterization.c").read_text())

    def test_every_sync_runs_under_state_lock(self):
        calls = [m.start() for m in re.finditer(r"status_sync_locked\(\);", self.main)]
        self.assertEqual(len(calls), 4)
        for call in calls:
            function_start = self.main.rfind("\n}\n", 0, call)
            self.assertGreater(self.main.rfind("xSemaphoreTake(state_lock", 0, call), function_start, call)
            # The next lock operation after the call releases the lock it runs under.
            after = self.main[call:]
            self.assertLess(after.index("xSemaphoreGive(state_lock);"),
                            after.find("xSemaphoreTake(state_lock") % (len(after) + 1), call)

    def test_boot_starts_with_the_led_off_and_green_only_after_ready(self):
        app_main = _function_body(self.main, "void app_main(void)")
        init = app_main.index("status_rgb_init();")
        self.assertLess(init, app_main.index('emit_event("boot"'))
        self.assertLess(init, app_main.index("start_wifi()"))
        ready = app_main.index('emit_event("ready"')
        section = app_main[ready:]
        self.assertIn("device_ready = true;", _locked_sections(section)[0])
        self.assertIn("status_sync_locked();", _locked_sections(section)[0])
        # Nothing before the ready event may mark the device ready.
        self.assertEqual(self.main.count("device_ready = true;"), 1)
        self.assertNotIn("device_ready = true;", app_main[:ready])
        # A failed access point returns before ready: the LED stays off.
        self.assertLess(app_main.index("return;"), ready)

    def test_led_is_off_before_the_run_starts(self):
        post = _function_body(self.main, "static esp_err_t runs_post(httpd_req_t *req)")
        begin = post.index("db_run_begin(&current_run")
        sync = post.index("status_sync_locked();", begin)
        self.assertLess(sync, post.index("xSemaphoreGive(state_lock);", begin))
        self.assertLess(sync, post.index("xTaskCreate(workload_task"))
        # The measurement window opens in the workload task, at phase_start.
        task = _function_body(self.main, "static void workload_task(void *unused)")
        self.assertNotIn("status_sync_locked", task[:task.index('emit_event("phase_start"')])

    def test_led_returns_only_after_the_measurement_ends(self):
        task = _function_body(self.main, "static void workload_task(void *unused)")
        finish = task.index("db_run_finish(&current_run, result")
        self.assertLess(task.index('emit_event("phase_end"'), finish)
        self.assertEqual(task.count("status_sync_locked();"), 1)
        self.assertGreater(task.index("status_sync_locked();"), finish)
        # A failed task creation finishes the run as fail, so the LED stays off.
        post = _function_body(self.main, "static esp_err_t runs_post(httpd_req_t *req)")
        failed = post[post.index("!= pdPASS"):]
        self.assertLess(failed.index('db_run_finish(&current_run, "fail"'), failed.index("status_sync_locked();"))

    def test_policy_is_shared_by_every_experiment_profile(self):
        sync = _function_body(self.main, "static void status_sync_locked(void)")
        self.assertNotIn("DB_EXPERIMENT", sync)
        run_c = (ROOT / "firmware/common/db_run.c").read_text()
        policy = _function_body(run_c, "bool db_status_ready(")
        self.assertNotIn("DB_EXPERIMENT", policy)
        self.assertIn('strcmp(run->result, "pass") == 0', policy)


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.driver = DRIVER_C.read_text()

    def test_driver_is_small_and_quiet(self):
        # Solid green or off: no task, timer, animation, heap use, or run-time logging.
        for forbidden in ("xTaskCreate", "esp_timer", "vTaskDelay", "malloc", "heap_caps", "ledc_",
                          "pcnt_", "loop_count = -1"):
            self.assertNotIn(forbidden, self.driver, forbidden)
        self.assertEqual(self.driver.count("ESP_LOG"), 1)
        self.assertIn("ESP_LOGW", _function_body(self.driver, "void status_rgb_init(void)"))
        self.assertEqual(re.findall(r"#define GREEN_LEVEL (\d+)", self.driver), ["16"])
        self.assertIn("const uint8_t grb[3] = {green, 0, 0};", self.driver)

    def test_driver_waits_for_the_led_to_latch(self):
        send = _function_body(self.driver, "static void send_frame(uint8_t green)")
        self.assertIn("rmt_tx_wait_all_done(channel", send)
        self.assertIn("esp_rom_delay_us(LATCH_US)", send)
        self.assertGreater(int(re.search(r"#define LATCH_US (\d+)", self.driver).group(1)), 280)

    def test_gpio_powered_led_is_unpowered_when_off(self):
        body = _function_body(self.driver, "void status_rgb_set(bool green)")
        off = body[body.index("} else {"):]
        self.assertLess(off.index("send_frame(0);"), off.index("set_power(false);"))
        init = _function_body(self.driver, "void status_rgb_init(void)")
        self.assertLess(init.index("set_power(false);"), init.index("rmt_new_tx_channel"))

    def test_resources_are_board_settings_not_experiment_settings(self):
        kconfig = KCONFIG.read_text()
        experiment = kconfig[kconfig.index("if DB_EXPERIMENT_FAN_CHARACTERIZATION\n"):]
        for name in ("DB_STATUS_RGB_GPIO", "DB_STATUS_RGB_POWER_GPIO", "DB_STATUS_RGB_POWER_ACTIVE_LEVEL"):
            self.assertIn(f"config {name}\n", kconfig)
            self.assertNotIn(f"config {name}\n", experiment)
        self.assertNotIn("DB_BOARD_RESERVED_GPIO", kconfig)


if __name__ == "__main__":
    unittest.main()
