"""Dependency-free DragonBench HTTP/JSON client."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class ClientError(RuntimeError):
    pass


# Mirrors firmware/common/include/db_fan.h; the firmware remains the authority.
FAN_PWM_HZ_MIN = 10
FAN_PWM_HZ_MAX = 50000
MAX_DURATION_MS = 3_600_000
SWEEP_ORDERS = ("up", "down", "up-down", "down-up")


class Client:
    def __init__(self, host: str, timeout: float = 10.0):
        self.base = host if "://" in host else f"http://{host}"
        self.base = self.base.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode()
                if response.headers.get_content_type() == "application/x-ndjson":
                    return [json.loads(line) for line in raw.splitlines() if line]
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            # Validation and conflict responses carry {"error": ...}; keep it.
            try:
                detail = json.loads(exc.read().decode()).get("error")
            except (ValueError, AttributeError, OSError):
                detail = None
            raise ClientError(f"HTTP {exc.code}: {detail}" if detail else str(exc)) from exc
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ClientError(str(exc)) from exc


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dragonbench")
    p.add_argument("--host", default="192.168.4.1")
    p.add_argument("--json", action="store_true", dest="machine")
    p.add_argument("--timeout", type=float, default=10.0)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    sub.add_parser("status")
    sub.add_parser("sensors")
    sub.add_parser("workloads")
    run = sub.add_parser("run")
    run.add_argument("workload")
    run.add_argument("--duration", type=float, default=30.0)
    run.add_argument("--target-host")
    run.add_argument("--port", type=int)
    run.add_argument("--rate", type=int, default=0)
    run.add_argument("--pwm-hz", type=int, help="FAN_PWM_HOLD only")
    run.add_argument("--sink-duty-pct", type=float, help="FAN_PWM_HOLD only")
    abort = sub.add_parser("abort")
    abort.add_argument("run_id")
    sub.add_parser("events")
    export = sub.add_parser("export")
    export.add_argument("run_id", nargs="?", default="latest")
    export.add_argument("--output", type=Path)
    traffic = sub.add_parser("traffic-peer")
    traffic.add_argument("--listen", default="0.0.0.0")
    traffic.add_argument("--port", type=int, required=True)
    traffic.add_argument("--mode", choices=("sink", "source", "echo"), required=True)
    traffic.add_argument("--duration", type=float, default=60.0)
    sweep = sub.add_parser(
        "fan-sweep",
        help="run one FAN_PWM_HOLD per sink-duty step (fan-characterization profile)",
        description="Every step is a separate run; the fixture releases the fan PWM line "
                    "between steps. No parameter has a default fan meaning.",
    )
    sweep.add_argument("--pwm-hz", type=int, required=True)
    sweep.add_argument("--low-pct", type=float, required=True, help="lowest sink duty, 0..100")
    sweep.add_argument("--high-pct", type=float, required=True, help="highest sink duty, 0..100")
    sweep.add_argument("--step-pct", type=float, required=True, help="sink duty step, 0.1 resolution")
    sweep.add_argument("--order", choices=SWEEP_ORDERS, required=True)
    sweep.add_argument("--hold-ms", type=int, required=True, help="FAN_PWM_HOLD duration per step")
    sweep.add_argument("--gap-ms", type=int, default=0, help="host pause between steps (line released)")
    sweep.add_argument("--output", type=Path, required=True, help="JSON results file, rewritten after every step")
    return p


def duty_tenths(value: float, name: str) -> int:
    """Sink duty in tenths of a percent, rejecting anything the firmware would."""
    if not 0 <= value <= 100:  # also rejects NaN
        raise ClientError(f"{name} must be 0..100 in 0.1 steps")
    tenths = round(value * 10)
    if abs(value * 10 - tenths) > 1e-6:
        raise ClientError(f"{name} must be 0..100 in 0.1 steps")
    return tenths


def sweep_steps(low_tenths: int, high_tenths: int, step_tenths: int, order: str) -> list[tuple[str, int]]:
    """Ordered (direction, sink duty tenths) steps. The far endpoint is always
    included, and an up-down/down-up turnaround point is held once."""
    if step_tenths <= 0:
        raise ClientError("step-pct must be greater than 0")
    if low_tenths > high_tenths:
        raise ClientError("low-pct must not exceed high-pct")
    up = list(range(low_tenths, high_tenths + 1, step_tenths))
    if up[-1] != high_tenths:
        up.append(high_tenths)
    down = up[::-1]
    if order == "up":
        return [("up", d) for d in up]
    if order == "down":
        return [("down", d) for d in down]
    if order == "up-down":
        return [("up", d) for d in up] + [("down", d) for d in down[1:]]
    if order == "down-up":
        return [("down", d) for d in down] + [("up", d) for d in up[1:]]
    raise ClientError(f"order must be one of {', '.join(SWEEP_ORDERS)}")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fan_sweep(args: argparse.Namespace, client: Client, sleep=time.sleep, clock=time.monotonic) -> dict[str, Any]:
    if not FAN_PWM_HZ_MIN <= args.pwm_hz <= FAN_PWM_HZ_MAX:
        raise ClientError(f"pwm-hz must be {FAN_PWM_HZ_MIN}..{FAN_PWM_HZ_MAX}")
    if not 1 <= args.hold_ms <= MAX_DURATION_MS:
        raise ClientError(f"hold-ms must be 1..{MAX_DURATION_MS}")
    if args.gap_ms < 0:
        raise ClientError("gap-ms must not be negative")
    steps = sweep_steps(duty_tenths(args.low_pct, "low-pct"), duty_tenths(args.high_pct, "high-pct"),
                        duty_tenths(args.step_pct, "step-pct"), args.order)

    device = client.request("GET", "/api/v1/device")
    if device.get("experiment_profile") != "fan-characterization":
        raise ClientError(f"device experiment profile is {device.get('experiment_profile')!r}, "
                          "not 'fan-characterization'; FAN_PWM_HOLD is unavailable")

    report: dict[str, Any] = {
        "schema": "dragonbench.fan_sweep/1",
        "source": "dut_reported",
        "status": "running",
        "started_utc": _utc_now(),
        "device": device,
        "sweep": {
            "pwm_hz": args.pwm_hz, "order": args.order, "low_pct": args.low_pct,
            "high_pct": args.high_pct, "step_pct": args.step_pct, "hold_ms": args.hold_ms,
            "gap_ms": args.gap_ms,
            "planned_sink_duty_pct": [tenths / 10 for _, tenths in steps],
        },
        "notes": "Each step is an independent FAN_PWM_HOLD run. The fan PWM line is released "
                 "between steps, so a step does not continue from the previous one. RPM is "
                 "present only when the device reports a configured PPR.",
        "steps": [],
        "external_measurements": None,
    }
    _write_json(args.output, report)
    active_run = None
    try:
        for index, (direction, tenths) in enumerate(steps):
            if index and args.gap_ms:
                sleep(args.gap_ms / 1000)
            body = {"workload": "FAN_PWM_HOLD", "duration_ms": args.hold_ms,
                    "pwm_hz": args.pwm_hz, "sink_duty_pct": tenths / 10}
            host_started = _utc_now()
            started = client.request("POST", "/api/v1/runs", body)
            active_run = started.get("run_id")
            if not active_run:
                raise ClientError(f"step {index}: device refused the run: {started.get('error', started)}")
            deadline = clock() + args.hold_ms / 1000 + 10.0
            while True:
                run = client.request("GET", f"/api/v1/runs/{active_run}")
                if run.get("state") == "complete":
                    break
                if clock() > deadline:
                    raise ClientError(f"step {index}: run {active_run} did not complete in time")
                sleep(0.2)
            run_id, active_run = active_run, None
            events = [e for e in client.request("GET", "/api/v1/events") if e.get("run_id") == run_id]
            by_kind = {e.get("event"): e for e in events}
            phase_start, phase_end = by_kind.get("phase_start", {}), by_kind.get("phase_end", {})
            report["steps"].append({
                "index": index,
                "direction": direction,
                "sink_duty_pct": tenths / 10,
                "run_id": run_id,
                "result": run.get("result"),
                "host_started_utc": host_started,
                "host_ended_utc": _utc_now(),
                "phase_start_seq": phase_start.get("seq"),
                "phase_start_uptime_ms": phase_start.get("uptime_ms"),
                "phase_end_seq": phase_end.get("seq"),
                "phase_end_uptime_ms": phase_end.get("uptime_ms"),
                "parameters": phase_end.get("parameters"),
                "metrics": phase_end.get("metrics"),
                "fault": by_kind.get("fault"),
            })
            _write_json(args.output, report)
            if run.get("result") != "pass":
                raise ClientError(f"step {index}: run {run_id} ended {run.get('result')}; sweep stopped")
    except (ClientError, KeyboardInterrupt) as exc:
        if active_run:
            try:
                client.request("POST", f"/api/v1/runs/{active_run}/abort", {})
            except ClientError:
                pass
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["error"] = str(exc) or type(exc).__name__
        report["ended_utc"] = _utc_now()
        _write_json(args.output, report)
        if isinstance(exc, KeyboardInterrupt):
            raise ClientError(f"sweep interrupted; partial results in {args.output}") from exc
        raise
    report["status"] = "complete"
    report["ended_utc"] = _utc_now()
    _write_json(args.output, report)
    return {"written": str(args.output), "status": "complete", "steps": len(report["steps"])}


def traffic_peer(bind_host: str, port: int, mode: str, duration: float) -> dict[str, Any]:
    if not 1 <= port <= 65535 or duration <= 0 or duration > 3600:
        raise ClientError("traffic peer requires port 1..65535 and duration >0..3600 seconds")
    tx = rx = 0
    block = bytes((i % 251 for i in range(4096)))
    deadline = time.monotonic() + duration
    with socket.socket(socket.AF_INET6 if ":" in bind_host else socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((bind_host, port))
        server.listen(1)
        server.settimeout(duration)
        conn, peer = server.accept()
        with conn:
            conn.settimeout(1.0)
            while time.monotonic() < deadline:
                try:
                    if mode in {"sink", "echo"}:
                        data = conn.recv(len(block))
                        if not data:
                            break
                        rx += len(data)
                        if mode == "echo":
                            conn.sendall(data)
                            tx += len(data)
                    else:
                        conn.sendall(block)
                        tx += len(block)
                except socket.timeout:
                    continue
    return {"peer": peer[0], "mode": mode, "bytes_tx": tx, "bytes_rx": rx}


def execute(args: argparse.Namespace, client: Client) -> Any:
    if args.command == "traffic-peer":
        return traffic_peer(args.listen, args.port, args.mode, args.duration)
    if args.command == "fan-sweep":
        return fan_sweep(args, client)
    if args.command == "discover":
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(args.host, 80)})
        except socket.gaierror as exc:
            raise ClientError(f"mDNS/DNS discovery failed for {args.host}: {exc}") from exc
        return {"hostname": args.host, "addresses": addresses}
    if args.command in {"status", "sensors", "workloads"}:
        return client.request("GET", f"/api/v1/{args.command}")
    if args.command == "run":
        if args.duration <= 0 or args.duration > 3600:
            raise ClientError("duration must be >0 and <=3600 seconds")
        if args.port is not None and not 1 <= args.port <= 65535:
            raise ClientError("port must be 1..65535")
        body: dict[str, Any] = {
            "workload": args.workload.upper(),
            "duration_ms": int(args.duration * 1000),
            "rate_bps": args.rate,
        }
        if args.target_host:
            body["host"] = args.target_host
        if args.port is not None:
            body["port"] = args.port
        if args.pwm_hz is not None:
            body["pwm_hz"] = args.pwm_hz
        if args.sink_duty_pct is not None:
            body["sink_duty_pct"] = duty_tenths(args.sink_duty_pct, "sink-duty-pct") / 10
        return client.request("POST", "/api/v1/runs", body)
    if args.command == "abort":
        return client.request("POST", f"/api/v1/runs/{args.run_id}/abort", {})
    if args.command == "events":
        return client.request("GET", "/api/v1/events")
    if args.command == "export":
        run_id = args.run_id
        if run_id == "latest":
            status = client.request("GET", "/api/v1/status")
            run_id = status.get("last_run_id") or status.get("run_id")
            if not run_id:
                raise ClientError("device has no run to export")
        payload = {
            "source": "dut_reported",
            "device": client.request("GET", "/api/v1/device"),
            "run": client.request("GET", f"/api/v1/runs/{run_id}"),
            "events": client.request("GET", "/api/v1/events"),
            "external_measurements": None,
        }
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return {"written": str(args.output), "run_id": run_id}
        return payload
    raise ClientError("unknown command")


def render(value: Any, machine: bool) -> str:
    if machine:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return json.dumps(value, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args, Client(args.host, args.timeout))
    except ClientError as exc:
        print(json.dumps({"error": str(exc)}) if args.machine else f"error: {exc}", file=sys.stderr)
        return 2
    print(render(result, args.machine))
    return 0
