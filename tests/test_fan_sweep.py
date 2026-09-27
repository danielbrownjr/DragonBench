import json
import tempfile
import unittest
from pathlib import Path

from cli.dragonbench.main import (
    ClientError, FAN_PWM_HZ_MAX, FAN_PWM_HZ_MIN, duty_tenths, execute, fan_sweep, parser, sweep_steps,
)


class FakeFanDevice:
    """Minimal stand-in for a fan-characterization device's HTTP API."""

    def __init__(self, fixture=True, results=None, polls_until_complete=1, refuse_at=None):
        self.fixture = fixture
        self.results = results or {}
        self.polls_until_complete = polls_until_complete
        self.refuse_at = refuse_at
        self.calls = []
        self.runs = {}
        self.events = []
        self.seq = 0

    def _emit(self, event, run_id, **fields):
        self.seq += 1
        self.events.append({"schema": 1, "event": event, "seq": self.seq, "uptime_ms": 1000 + self.seq,
                            "run_id": run_id, "phase": "FAN_PWM_HOLD", **fields})

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/v1/device":
            return {"product": "DragonBench", "fan_control_capability": False,
                    "experiment_profile": "fan-characterization" if self.fixture else "baseline",
                    "bench_stimulus": {"fan_pwm_fixture": self.fixture}}
        if method == "POST" and path == "/api/v1/runs":
            index = len(self.runs)
            if index == self.refuse_at:
                raise ClientError("HTTP 400: pwm_hz must be 10..50000")
            run_id = f"run-{index}"
            self.runs[run_id] = {"polls": 0, "body": body, "result": self.results.get(index, "pass")}
            self._emit("phase_start", run_id, parameters={"sink_duty_pct": body.get("sink_duty_pct")})
            return {"run_id": run_id, "state": "running"}
        if method == "GET" and path.startswith("/api/v1/runs/"):
            run_id = path.rsplit("/", 1)[1]
            run = self.runs[run_id]
            run["polls"] += 1
            if run["polls"] < self.polls_until_complete:
                return {"run_id": run_id, "state": "running", "result": "running"}
            if "done" not in run:
                run["done"] = True
                metrics = {"tach_edges": 100, "window_us": run["body"]["duration_ms"] * 1000,
                           "edge_hz": 100.0, "ppr": None, "rpm": None, "released_us": 5}
                self._emit("phase_end", run_id, result=run["result"], metrics=metrics,
                           parameters={"sink_duty_pct": run["body"]["sink_duty_pct"]})
                self._emit("run_complete", run_id, result=run["result"])
            return {"run_id": run_id, "state": "complete", "result": run["result"]}
        if method == "POST" and path.endswith("/abort"):
            return {"state": "aborting"}
        if path == "/api/v1/events":
            return list(self.events)
        raise AssertionError(f"unexpected request {method} {path}")


def sweep_args(output, *extra):
    return parser().parse_args(["fan-sweep", "--pwm-hz", "25000", "--low-pct", "20", "--high-pct", "40",
                                "--step-pct", "10", "--hold-ms", "2000", "--output", str(output), *extra])


class SweepOrderTests(unittest.TestCase):
    def test_up_and_down(self):
        self.assertEqual(sweep_steps(200, 400, 100, "up"), [("up", 200), ("up", 300), ("up", 400)])
        self.assertEqual(sweep_steps(200, 400, 100, "down"), [("down", 400), ("down", 300), ("down", 200)])

    def test_turnaround_is_held_once(self):
        self.assertEqual(sweep_steps(0, 200, 100, "up-down"),
                         [("up", 0), ("up", 100), ("up", 200), ("down", 100), ("down", 0)])
        self.assertEqual(sweep_steps(0, 200, 100, "down-up"),
                         [("down", 200), ("down", 100), ("down", 0), ("up", 100), ("up", 200)])

    def test_far_endpoint_always_included(self):
        self.assertEqual([d for _, d in sweep_steps(0, 250, 100, "up")], [0, 100, 200, 250])
        self.assertEqual([d for _, d in sweep_steps(0, 250, 100, "down")], [250, 200, 100, 0])

    def test_single_point(self):
        self.assertEqual(sweep_steps(500, 500, 10, "up-down"), [("up", 500)])

    def test_invalid_ranges(self):
        with self.assertRaises(ClientError):
            sweep_steps(400, 200, 100, "up")
        with self.assertRaises(ClientError):
            sweep_steps(0, 200, 0, "up")
        with self.assertRaises(ClientError):
            sweep_steps(0, 200, 100, "sideways")

    def test_duty_resolution_matches_firmware(self):
        self.assertEqual(duty_tenths(33.3, "x"), 333)
        self.assertEqual(duty_tenths(100, "x"), 1000)
        for bad in (-0.1, 100.1, 33.35, float("nan")):
            with self.assertRaises(ClientError):
                duty_tenths(bad, "x")


class FanSweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name) / "sweep.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_sweep(self, device, *extra):
        return fan_sweep(sweep_args(self.output, *extra), device, sleep=lambda _: None)

    def test_up_down_sweep_posts_holds_in_order_and_writes_results(self):
        device = FakeFanDevice(polls_until_complete=2)
        summary = self.run_sweep(device, "--order", "up-down")
        posts = [body for method, path, body in device.calls if (method, path) == ("POST", "/api/v1/runs")]
        self.assertEqual([p["sink_duty_pct"] for p in posts], [20.0, 30.0, 40.0, 30.0, 20.0])
        for body in posts:
            self.assertEqual(body["workload"], "FAN_PWM_HOLD")
            self.assertEqual(body["pwm_hz"], 25000)
            self.assertEqual(body["duration_ms"], 2000)
        report = json.loads(self.output.read_text())
        self.assertEqual(summary["steps"], 5)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["schema"], "dragonbench.fan_sweep/1")
        self.assertIsNone(report["external_measurements"])
        self.assertEqual([s["direction"] for s in report["steps"]], ["up", "up", "up", "down", "down"])
        self.assertEqual(report["sweep"]["planned_sink_duty_pct"], [20.0, 30.0, 40.0, 30.0, 20.0])
        first = report["steps"][0]
        self.assertEqual(first["run_id"], "run-0")
        self.assertLess(first["phase_start_seq"], first["phase_end_seq"])
        self.assertIsNone(first["metrics"]["rpm"])
        self.assertIsNone(first["metrics"]["ppr"])

    def test_refuses_normal_build_before_any_run(self):
        device = FakeFanDevice(fixture=False)
        with self.assertRaises(ClientError):
            self.run_sweep(device, "--order", "up")
        self.assertFalse([c for c in device.calls if c[0] == "POST"])

    def test_failed_step_stops_sweep_and_keeps_partial_results(self):
        device = FakeFanDevice(results={1: "fail"})
        with self.assertRaises(ClientError):
            self.run_sweep(device, "--order", "up")
        report = json.loads(self.output.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual([s["result"] for s in report["steps"]], ["pass", "fail"])
        self.assertEqual(len([c for c in device.calls if c[:2] == ("POST", "/api/v1/runs")]), 2)

    def test_device_refusal_is_reported(self):
        device = FakeFanDevice(refuse_at=0)
        with self.assertRaises(ClientError):
            self.run_sweep(device, "--order", "up")
        self.assertEqual(json.loads(self.output.read_text())["status"], "failed")

    def test_timeout_aborts_active_run(self):
        device = FakeFanDevice(polls_until_complete=10**9)
        ticks = iter(range(0, 10**6, 5))
        args = sweep_args(self.output, "--order", "up")
        with self.assertRaises(ClientError):
            fan_sweep(args, device, sleep=lambda _: None, clock=lambda: next(ticks))
        self.assertIn(("POST", "/api/v1/runs/run-0/abort", {}), device.calls)

    def test_interrupt_aborts_active_run_and_records_partial(self):
        device = FakeFanDevice(polls_until_complete=3)

        def interrupt(_):
            raise KeyboardInterrupt

        with self.assertRaises(ClientError):
            fan_sweep(sweep_args(self.output, "--order", "up"), device, sleep=interrupt)
        self.assertIn(("POST", "/api/v1/runs/run-0/abort", {}), device.calls)
        self.assertEqual(json.loads(self.output.read_text())["status"], "interrupted")

    def test_parameter_validation_before_network(self):
        for extra in (["--pwm-hz", str(FAN_PWM_HZ_MIN - 1)], ["--pwm-hz", str(FAN_PWM_HZ_MAX + 1)],
                      ["--hold-ms", "0"], ["--hold-ms", "3600001"], ["--gap-ms", "-1"],
                      ["--step-pct", "0.05"], ["--high-pct", "100.5"]):
            device = FakeFanDevice()
            args = sweep_args(self.output, "--order", "up", *extra)
            with self.assertRaises(ClientError, msg=extra):
                fan_sweep(args, device, sleep=lambda _: None)
            self.assertEqual(device.calls, [], extra)

    def test_run_command_passes_fan_parameters(self):
        device = FakeFanDevice()
        args = parser().parse_args(["run", "fan_pwm_hold", "--duration", "3", "--pwm-hz", "25000",
                                    "--sink-duty-pct", "35.5"])
        execute(args, device)
        body = device.calls[0][2]
        self.assertEqual(body["workload"], "FAN_PWM_HOLD")
        self.assertEqual((body["pwm_hz"], body["sink_duty_pct"], body["duration_ms"]), (25000, 35.5, 3000))

    def test_run_command_omits_fan_parameters_by_default(self):
        device = FakeFanDevice()
        execute(parser().parse_args(["run", "IDLE", "--duration", "1"]), device)
        self.assertNotIn("pwm_hz", device.calls[0][2])
        self.assertNotIn("sink_duty_pct", device.calls[0][2])


if __name__ == "__main__":
    unittest.main()
