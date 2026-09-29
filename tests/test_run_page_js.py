import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_contract import _firmware_page

# Runs the /run page script against a fake DOM, a fake clock, and a scripted
# device, and records what the operator would see after each step.
HARNESS = r"""
const PAGE = %s;
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };
function makeEl() {
  return {
    textContent: '', value: '', hidden: false, disabled: false, dataset: {}, className: '', type: '',
    children: [], listeners: {},
    get firstChild() { return this.children[0] || null; },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children.splice(this.children.indexOf(c), 1); return c; },
    addEventListener(t, fn) { this.listeners[t] = fn; },
  };
}
function page(device) {
  const roles = {};
  const el = name => roles[name] || (roles[name] = makeEl());
  el('run-duration').value = '30';
  el('run-rate').value = '0';
  const document = {
    querySelector(sel) { return el(sel.match(/data-role="([^"]+)"/)[1]); },
    createElement() { return makeEl(); },
  };
  let now = 1000000;
  const intervals = [];
  const posts = [];
  const reply = r => Promise.resolve({ ok: r.code >= 200 && r.code < 300, status: r.code, json: () => Promise.resolve(r.body) });
  const fetch = (url, opts) => {
    if (device.offline) return Promise.reject(new Error('offline'));
    if (opts && opts.method === 'POST') {
      posts.push({ url, body: opts.body ? JSON.parse(opts.body) : null });
      const r = url === '/api/v1/runs' ? device.post : device.abort;
      if (r === 'hold') return new Promise(resolve => { device.release = r2 => resolve(reply(r2)); });
      return reply(r);
    }
    if (url === '/api/v1/status') return reply({ code: 200, body: JSON.parse(JSON.stringify(device.status)) });
    if (url === '/api/v1/workloads') return reply({ code: 200, body: { workloads: device.workloads } });
    return reply({ code: 404, body: {} });
  };
  const run = new Function('document', 'fetch', 'setInterval', 'setTimeout', 'clearTimeout', 'AbortController', 'Date', PAGE);
  run(document, fetch, fn => intervals.push(fn), () => 0, () => {},
      class { constructor() { this.signal = {}; } abort() {} }, { now: () => now });
  const buttons = () => {
    const out = {};
    el('run-workloads').children.forEach(row => row.children.forEach(c => {
      if (c.dataset.workload) out[c.dataset.workload] = c;
    }));
    return out;
  };
  const rows = () => el('run-workloads').children.map(row => row.children.map(c => c.textContent).join(' | '));
  return {
    el, posts, buttons, rows,
    async tick(ms) { now += ms; intervals[0](); intervals[1](); await flush(); },
    async wait(ms) { now += ms; intervals[1](); await flush(); },
    async click(id) { const b = buttons()[id]; if (b && !b.disabled) b.listeners.click(); await flush(); },
    async forceClick(id) { buttons()[id].listeners.click(); await flush(); },
    async abort() { const a = el('run-abort'); if (!a.hidden && !a.disabled) a.listeners.click(); await flush(); },
    snap() {
      const b = buttons();
      const disabled = {};
      Object.keys(b).forEach(k => { disabled[k] = b[k].disabled; });
      return {
        state: el('run-state').textContent, status: el('run-state').dataset.status,
        workload: el('run-workload').textContent, id: el('run-id').textContent,
        device: el('run-device').textContent, freshness: el('run-freshness').textContent,
        message: el('run-message').textContent, abortHidden: el('run-abort').hidden,
        disabled, posts: posts.length,
      };
    },
  };
}
const WORKLOADS = [
  { id: 'BOOT', status: 'available' }, { id: 'IDLE', status: 'available' },
  { id: 'WIFI_ASSOCIATED_IDLE', status: 'available' }, { id: 'NET_TX', status: 'available' },
  { id: 'NET_RX', status: 'available' }, { id: 'NET_BIDIRECTIONAL', status: 'available' },
  { id: 'CPU_STRESS', status: 'available' }, { id: 'FLASH_WRITE', status: 'available' },
  { id: 'NVS_WRITE', status: 'available' }, { id: 'OTA_PARTITION_WRITE', status: 'available' },
  { id: 'CONTROLLED_REBOOT', status: 'available' }, { id: 'FAN_PWM_HOLD', status: 'available' },
  { id: 'BLE_STRESS', status: 'unsupported' },
];
const st = (run_state, workload, run_id, result, extra) =>
  Object.assign({ run_state, workload, run_id, result, uptime_ms: 1 }, extra || {});
const IDLE = st('idle', 'IDLE', '', 'none');
function device(status) { return { status, workloads: WORKLOADS, post: null, abort: null, offline: false }; }

(async () => {
  const out = {};

  { // 1, 2, 3, 10, 11: start, device-confirmed running, pass, duplicate protection, re-enable
    const d = device(IDLE); const p = page(d); await p.tick(0);
    const s = [p.snap()];
    d.post = 'hold';
    await p.click('CPU_STRESS'); s.push(p.snap());
    await p.forceClick('CPU_STRESS'); await p.click('NVS_WRITE'); s.push(p.snap());
    d.status = st('running', 'CPU_STRESS', 'r1', 'none');
    d.release({ code: 201, body: { run_id: 'r1', state: 'running' } }); await flush(); s.push(p.snap());
    await p.forceClick('NVS_WRITE'); s.push(p.snap());
    d.status = st('complete', 'CPU_STRESS', 'r1', 'pass');
    await p.tick(2000); s.push(p.snap());
    await p.tick(2000); await p.tick(2000); await p.tick(2000); s.push(p.snap());
    out.start_pass = { snaps: s, body: p.posts[0].body };
  }
  { // POST acknowledged but the device does not (yet) report the run: never RUNNING
    const d = device(IDLE); const p = page(d); await p.tick(0);
    d.post = { code: 201, body: { run_id: 'r2', state: 'running' } };
    await p.click('IDLE');
    out.ack_only = p.snap();
  }
  { // 4: fail
    const d = device(st('running', 'FLASH_WRITE', 'r3', 'none')); const p = page(d); await p.tick(0);
    const a = p.snap();
    d.status = st('complete', 'FLASH_WRITE', 'r3', 'fail'); await p.tick(2000);
    out.fail = [a, p.snap()];
  }
  { // 5: abort
    const d = device(st('running', 'IDLE', 'r4', 'none')); const p = page(d); await p.tick(0);
    const s = [p.snap()];
    d.abort = 'hold';
    await p.abort(); s.push(p.snap());
    d.status = st('aborting', 'IDLE', 'r4', 'none');
    d.release({ code: 200, body: { run_id: 'r4', state: 'aborting' } }); await flush(); s.push(p.snap());
    d.status = st('complete', 'IDLE', 'r4', 'aborted'); await p.tick(2000); s.push(p.snap());
    out.abort = { snaps: s, url: p.posts[0].url };
  }
  { // 6, 7: device rejections
    const d = device(IDLE); const p = page(d); await p.tick(0);
    d.post = { code: 400, body: { error: 'duration_ms must be 1..3600000' } };
    await p.click('NVS_WRITE'); const a = p.snap();
    d.post = { code: 409, body: { error: 'run already active' } };
    await p.click('NVS_WRITE'); const b = p.snap();
    out.rejected = [a, b];
  }
  { // browser-side completeness checks never POST
    const d = device(IDLE); const p = page(d); await p.tick(0);
    await p.click('NET_TX'); const a = p.snap();
    p.el('run-host').value = '192.168.4.2'; p.el('run-port').value = '99999';
    await p.click('NET_TX'); const b = p.snap();
    p.el('run-duration').value = '0'; await p.click('IDLE'); const c = p.snap();
    p.el('run-duration').value = '2.5'; p.el('run-port').value = '5201'; p.el('run-rate').value = '800000';
    d.post = { code: 201, body: { run_id: 'r5', state: 'running' } };
    await p.click('NET_TX');
    out.validation = { snaps: [a, b, c], body: p.posts[0].body, posts: p.posts.length };
  }
  { // 8, 9, 11: loss of contact while running, then reconnect into the still-active run
    const d = device(st('running', 'NET_RX', 'r6', 'none')); const p = page(d); await p.tick(0);
    const s = [p.snap()];
    d.offline = true;
    await p.tick(2000); s.push(p.snap());
    await p.tick(4000); s.push(p.snap());
    await p.tick(10000); s.push(p.snap());
    d.offline = false; await p.tick(2000); s.push(p.snap());
    d.status = st('complete', 'NET_RX', 'r6', 'pass'); d.offline = true;
    await p.tick(6000); s.push(p.snap());
    d.offline = false; d.status = IDLE; await p.tick(2000); s.push(p.snap());
    out.loss = s;
  }
  { // 9: a fresh page opened while a run is already active
    const d = device(st('running', 'OTA_PARTITION_WRITE', 'r7', 'none')); const p = page(d); await p.tick(0);
    out.fresh_active = p.snap();
  }
  { // never reached the device
    const d = device(IDLE); d.offline = true; const p = page(d); await p.tick(0);
    out.unreachable = p.snap();
  }
  { // 12: workloads this page cannot build a request for
    const d = device(IDLE); const p = page(d); await p.tick(0);
    out.unknown = { rows: p.rows(), buttons: Object.keys(p.buttons()) };
  }
  { // 13: CONTROLLED_REBOOT disconnect and return
    const d = device(IDLE); const p = page(d); await p.tick(0);
    d.status = st('running', 'CONTROLLED_REBOOT', 'r9', 'none');
    d.post = { code: 201, body: { run_id: 'r9', state: 'running' } };
    await p.click('CONTROLLED_REBOOT'); const s = [p.snap()];
    d.offline = true; await p.tick(6000); s.push(p.snap());
    await p.tick(10000); s.push(p.snap());
    d.offline = false; d.status = st('idle', 'IDLE', '', 'none', { previous_reboot_run_id: 'r9' });
    await p.tick(2000); s.push(p.snap());
    out.reboot = { snaps: s, rows: p.rows() };
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

TIMED = ["BOOT", "IDLE", "WIFI_ASSOCIATED_IDLE", "CPU_STRESS", "FLASH_WRITE", "NVS_WRITE",
         "OTA_PARTITION_WRITE", "CONTROLLED_REBOOT"]
NETWORK = ["NET_TX", "NET_RX", "NET_BIDIRECTIONAL"]


@unittest.skipUnless(shutil.which("node") or os.environ.get("DRAGONBENCH_REQUIRE_NODE"),
                     "needs Node.js to run the /run page script")
class RunPageBehaviourTests(unittest.TestCase):
    """What the operator sees on /run, driven only by scripted device responses."""

    @classmethod
    def setUpClass(cls):
        html = _firmware_page("run_page")
        script = html[html.index("<script>") + len("<script>"):html.index("</script>")]
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.js"
            harness.write_text(HARNESS % json.dumps(script), encoding="utf-8")
            result = subprocess.run(["node", str(harness)], capture_output=True, text=True,
                                    encoding="utf-8", timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def assertButtons(self, snap, disabled):
        self.assertTrue(snap["disabled"], snap)
        for workload, value in snap["disabled"].items():
            self.assertEqual(value, disabled, (workload, snap))

    def test_idle_click_shows_starting_only_while_the_request_is_in_flight(self):
        ready, starting = self.out["start_pass"]["snaps"][:2]
        self.assertEqual(ready["state"], "READY")
        self.assertButtons(ready, False)
        self.assertEqual(starting["status"], "starting")
        self.assertTrue(starting["state"].startswith("STARTING"), starting)
        self.assertIn("CPU_STRESS", starting["state"])
        self.assertButtons(starting, True)
        self.assertTrue(starting["abortHidden"])

    def test_start_request_carries_only_the_known_fields(self):
        self.assertEqual(self.out["start_pass"]["body"], {"workload": "CPU_STRESS", "duration_ms": 30000})

    def test_running_comes_only_from_device_status(self):
        running = self.out["start_pass"]["snaps"][3]
        self.assertEqual(running["status"], "running")
        self.assertTrue(running["state"].startswith("RUNNING"), running)
        self.assertIn("CPU_STRESS", running["state"])
        self.assertEqual(running["id"], "r1")
        self.assertFalse(running["abortHidden"])
        self.assertButtons(running, True)
        self.assertEqual(running["message"], "")

    def test_post_acknowledgement_alone_is_not_running(self):
        snap = self.out["ack_only"]
        self.assertEqual(snap["state"], "READY")
        self.assertNotEqual(snap["status"], "running")
        self.assertIn("r2", snap["message"])
        self.assertIn("waiting for the device", snap["message"])

    def test_duplicate_clicks_send_one_request(self):
        snaps = self.out["start_pass"]["snaps"]
        self.assertEqual(snaps[2]["posts"], 1)
        self.assertEqual(snaps[4]["posts"], 1)

    def test_pass_is_shown_and_persists_while_the_device_reports_it(self):
        passed, later = self.out["start_pass"]["snaps"][5:7]
        for snap in (passed, later):
            self.assertEqual(snap["status"], "pass")
            self.assertTrue(snap["state"].startswith("PASS"), snap)
            self.assertIn("CPU_STRESS", snap["state"])
            self.assertEqual(snap["id"], "r1")
            self.assertButtons(snap, False)
            self.assertTrue(snap["abortHidden"])

    def test_fail_is_shown(self):
        running, failed = self.out["fail"]
        self.assertEqual(running["status"], "running")
        self.assertEqual(failed["status"], "fail")
        self.assertTrue(failed["state"].startswith("FAIL"), failed)
        self.assertIn("FLASH_WRITE", failed["state"])
        self.assertButtons(failed, False)

    def test_abort_is_driven_by_device_state(self):
        running, requested, aborting, aborted = self.out["abort"]["snaps"]
        self.assertEqual(self.out["abort"]["url"], "/api/v1/runs/r4/abort")
        self.assertFalse(running["abortHidden"])
        self.assertEqual(requested["status"], "running")
        self.assertEqual(aborting["status"], "aborting")
        self.assertTrue(aborting["state"].startswith("ABORTING"), aborting)
        self.assertTrue(aborting["abortHidden"])
        self.assertButtons(aborting, True)
        self.assertEqual(aborted["status"], "aborted")
        self.assertTrue(aborted["state"].startswith("ABORTED"), aborted)
        self.assertButtons(aborted, False)

    def test_device_validation_rejection_is_shown(self):
        snap = self.out["rejected"][0]
        self.assertIn("HTTP 400", snap["message"])
        self.assertIn("duration_ms must be 1..3600000", snap["message"])
        self.assertEqual(snap["state"], "READY")
        self.assertButtons(snap, False)

    def test_device_conflict_rejection_is_shown(self):
        snap = self.out["rejected"][1]
        self.assertIn("HTTP 409", snap["message"])
        self.assertIn("run already active", snap["message"])
        self.assertEqual(snap["state"], "READY")

    def test_incomplete_input_is_caught_before_posting(self):
        v = self.out["validation"]
        self.assertIn("host", v["snaps"][0]["message"])
        self.assertIn("port", v["snaps"][1]["message"])
        self.assertIn("Duration", v["snaps"][2]["message"])
        self.assertEqual([s["posts"] for s in v["snaps"]], [0, 0, 0])
        self.assertEqual(v["posts"], 1)
        self.assertEqual(v["body"], {"workload": "NET_TX", "duration_ms": 2500,
                                     "host": "192.168.4.2", "port": 5201, "rate_bps": 800000})

    def test_lost_contact_never_leaves_running_painted(self):
        live, recent, stale, lost, back, stale_pass, ready = self.out["loss"]
        self.assertEqual(live["status"], "running")
        self.assertEqual(recent["status"], "running")
        self.assertEqual(stale["state"], "STALE")
        self.assertEqual(lost["state"], "DISCONNECTED")
        for snap in (stale, lost):
            self.assertTrue(snap["abortHidden"])
            self.assertButtons(snap, True)
            self.assertIn("last report", snap["freshness"])
        self.assertEqual(back["status"], "running")
        self.assertIn("NET_RX", back["state"])
        self.assertEqual(back["id"], "r6")

    def test_controls_reenable_only_on_fresh_device_state(self):
        stale_pass, ready = self.out["loss"][5:7]
        self.assertEqual(stale_pass["state"], "STALE")
        self.assertButtons(stale_pass, True)
        self.assertEqual(ready["state"], "READY")
        self.assertButtons(ready, False)

    def test_page_opened_during_a_run_shows_it(self):
        snap = self.out["fresh_active"]
        self.assertEqual(snap["status"], "running")
        self.assertIn("OTA_PARTITION_WRITE", snap["state"])
        self.assertEqual(snap["id"], "r7")
        self.assertButtons(snap, True)
        self.assertFalse(snap["abortHidden"])

    def test_unreachable_device_is_disconnected(self):
        snap = self.out["unreachable"]
        self.assertEqual(snap["state"], "DISCONNECTED")
        self.assertEqual(snap["disabled"], {})

    def test_only_workloads_with_a_known_request_get_a_start_button(self):
        self.assertEqual(sorted(self.out["unknown"]["buttons"]), sorted(TIMED + NETWORK))
        rows = self.out["unknown"]["rows"]
        fan = next(r for r in rows if r.startswith("FAN_PWM_HOLD"))
        self.assertIn("no controls on this page yet", fan)
        ble = next(r for r in rows if r.startswith("BLE_STRESS"))
        self.assertIn("not supported", ble)

    def test_controlled_reboot_disconnect_is_not_a_failure(self):
        running, stale, lost, back = self.out["reboot"]["snaps"]
        self.assertIn("CONTROLLED_REBOOT", running["state"])
        self.assertEqual(stale["state"], "STALE")
        self.assertEqual(lost["state"], "DISCONNECTED")
        for snap in (stale, lost):
            self.assertNotIn("FAIL", snap["state"])
        self.assertEqual(back["state"], "READY")
        self.assertIn("rebooted by run r9", back["device"])
        self.assertButtons(back, False)
        reboot_row = next(r for r in self.out["reboot"]["rows"] if r.startswith("CONTROLLED_REBOOT"))
        self.assertIn("reboots the device", reboot_row)


if __name__ == "__main__":
    unittest.main()
