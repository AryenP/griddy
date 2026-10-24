"""A laptop that joins the Brownout fleet as a real, measured site (Windows; Python standard library only).

On the laptop, from the repo folder, unplugged (the battery reports its draw only on battery):

    python fleet/agent.py --mac http://<mac LAN address>:8080 --site <id from config/fleet.yaml> --calibrate
    python fleet/agent.py --mac http://<mac LAN address>:8080 --site <id>

What it does:
  meter   the battery's own power reading (WMI BatteryStatus.DischargeRate, mW, summed over batteries), once a
          second, from one long-running PowerShell reader. Whole device, screen included. Plugged in, the
          battery reports no draw, so the agent reports no watts rather than a wrong number.
  job     real CPU work: lzma-compress this laptop's Python standard library in 1 MB chunks on every core,
          counting megabytes compressed (the output is discarded). It runs only while the Mac's plan says run.
  control every second: POST /api/sites/<id>/beat with the watts and the job's progress; the reply says run or
          pause. If the Mac does not answer for --failsafe-s seconds, the job pauses: a laptop that lost its
          dispatcher never keeps drawing power nobody planned.
  --calibrate  measures idle and job watts and the job's rate on this laptop and sends them to the Mac
          (POST /api/sites/<id>/calibration), like `make calibrate` on the Mac.
"""
from __future__ import annotations

import argparse
import json
import lzma
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNK = 1 << 20                      # 1 MB of source text per compression call
STATE_DIR = Path("runs") / "fleet"   # runs/ is gitignored: local progress survives a restart

PS_READER = r"""
$ErrorActionPreference = 'SilentlyContinue'
while ($true) {
  $all = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus)
  $mw = [int](($all | Measure-Object -Property DischargeRate -Sum).Sum)
  $pl = (@($all | Where-Object { $_.PowerOnline }).Count -gt 0).ToString().ToLower()
  [Console]::Out.WriteLine('{"mw": ' + $mw + ', "plugged": ' + $pl + ', "batteries": ' + $all.Count + '}')
  [Console]::Out.Flush()
  Start-Sleep -Milliseconds 1000
}
"""


class BatteryMeter:
    """Latest battery reading: watts (None when plugged in or no battery) and when it was read."""

    def __init__(self):
        if os.name != "nt":
            raise SystemExit("the fleet meter reads the Windows battery (WMI); run this on the Windows laptop")
        self.watts: float | None = None
        self.plugged: bool | None = None
        self.t: float | None = None
        self.changed_t: float | None = None     # when the reading last changed: about once a minute on some laptops
        self.note = "no reading yet"
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_READER],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.t, self.plugged = time.time(), bool(d.get("plugged"))
            if d.get("mw") != getattr(self, "_last_mw", None):
                self.changed_t, self._last_mw = self.t, d.get("mw")
            if not d.get("batteries"):
                self.watts, self.note = None, "no battery reported by WMI"
            elif self.plugged:
                self.watts, self.note = None, "plugged in: the battery reports its draw only on battery"
            else:
                self.watts, self.note = d["mw"] / 1000.0, "battery discharge rate (WMI BatteryStatus)"

    def stop(self):
        self.proc.terminate()


class CompressJob:
    """lzma-compress the Python standard library on every core while `running` is set."""

    def __init__(self, site: str, threads: int):
        self.state_path = STATE_DIR / f"{site}.json"
        self.done_mb = self._load()
        self.running = threading.Event()
        self.lock = threading.Lock()
        self.data = self._corpus()
        self.threads = threads
        self._recent: list[tuple[float, float]] = []
        for k in range(threads):
            threading.Thread(target=self._work, args=(k,), daemon=True).start()

    @staticmethod
    def _corpus() -> list[bytes]:
        stdlib = Path(sysconfig.get_paths()["stdlib"])
        blob = b"".join(p.read_bytes() for p in sorted(stdlib.rglob("*.py")) if p.is_file())
        return [blob[i:i + CHUNK] for i in range(0, len(blob), CHUNK)]

    def _load(self) -> float:
        try:
            return float(json.loads(self.state_path.read_text())["done_mb"])
        except (OSError, ValueError, KeyError):
            return 0.0

    def save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"done_mb": self.done_mb}))

    def _work(self, k: int):
        i = k
        while True:
            self.running.wait()
            chunk = self.data[i % len(self.data)]
            lzma.compress(chunk, preset=6)          # releases the GIL: every thread uses its own core
            with self.lock:
                self.done_mb += len(chunk) / 1e6
                self._recent.append((time.time(), self.done_mb))
            i += self.threads

    def rate_mb_s(self, window: float = 10.0) -> float | None:
        now = time.time()
        with self.lock:
            self._recent = [(t, d) for t, d in self._recent if t >= now - window]
            pts = list(self._recent)
        if len(pts) < 2 or pts[-1][0] - pts[0][0] <= 0:
            return 0.0 if not self.running.is_set() else None
        return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


TOKEN = os.environ.get("BROWNOUT_FLEET_TOKEN", "")   # or --token; the Mac's FLEET_TOKEN


def post(url: str, body: dict, timeout: float = 3.0) -> dict:
    headers = {"content-type": "application/json"}
    if TOKEN:
        headers["X-Brownout-Fleet-Token"] = TOKEN
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def machine() -> str:
    return f"{platform.node()} {platform.machine()} {platform.system()} {platform.release()}"


def calibrate(args, meter: BatteryMeter, job: CompressJob) -> int:
    """Idle window, then the job on every core; the battery reading averaged over each (warm-up dropped)."""
    def window(seconds: float) -> list[float]:
        xs, end, last_t = [], time.time() + seconds, None
        while time.time() < end:
            if meter.t != last_t and meter.watts is not None:
                xs.append(meter.watts)
                last_t = meter.t
            time.sleep(0.2)
        return xs

    print(f"calibrating {args.site} on {machine()}: idle {args.window_s} s, then the job {args.window_s} s")
    time.sleep(3)
    if meter.watts is None:
        print(f"cannot calibrate: {meter.note}")
        return 1
    job.running.clear()
    idle = window(args.window_s)
    job.running.set()
    time.sleep(args.warmup_s)
    start_mb, start_t = job.done_mb, time.time()
    busy = window(args.window_s)
    rate = (job.done_mb - start_mb) / (time.time() - start_t)
    job.running.clear()
    job.save()
    if len(idle) < args.window_s / 4 or len(busy) < args.window_s / 4:
        print(f"too few battery readings (idle {len(idle)}, job {len(busy)}): the reading updates too rarely")
        return 1
    result = {"idle_w": statistics.fmean(idle), "delta_w": max(0.0, statistics.fmean(busy) - statistics.fmean(idle)),
              "rate_mb_s": rate, "samples": [len(idle), len(busy)], "window_s": args.window_s,
              "threads": job.threads, "measured_at": time.time(), "machine": machine(),
              "meter": "Windows battery discharge rate (WMI BatteryStatus), whole device"}
    print(json.dumps(result, indent=1))
    reply = post(f"{args.mac}/api/sites/{args.site}/calibration", result)
    print("sent to the Mac:", reply.get("status", reply))
    return 0


def run(args, meter: BatteryMeter, job: CompressJob) -> int:
    print(f"site {args.site} on {machine()} -> {args.mac}; {job.threads} threads; Ctrl-C to stop")
    last_ok, last_save = time.time(), time.time()
    while True:
        body = {"t": time.time(), "watts": meter.watts, "meter_t": meter.t, "meter_changed_t": meter.changed_t,
                "meter_note": meter.note,
                "plugged": meter.plugged, "running": job.running.is_set(), "done_mb": job.done_mb,
                "rate_mb_s": job.rate_mb_s(), "machine": machine()}
        try:
            plan = post(f"{args.mac}/api/sites/{args.site}/beat", body)
            last_ok = time.time()
            (job.running.set if plan.get("run") else job.running.clear)()
        except (urllib.error.URLError, OSError, ValueError) as e:
            if time.time() - last_ok > args.failsafe_s and job.running.is_set():
                job.running.clear()
                print(f"no answer from the Mac for {args.failsafe_s} s ({e}): job paused")
        if time.time() - last_save > 10:
            job.save()
            last_save = time.time()
        w = "—" if meter.watts is None else f"{meter.watts:.1f} W"
        print(f"\r{time.strftime('%H:%M:%S')}  {w:>8}  job {'running' if job.running.is_set() else 'paused '}"
              f"  {job.done_mb:9.1f} MB", end="", flush=True)
        time.sleep(1.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mac", required=True, help="the Mac's address, e.g. http://10.0.6.240:8080")
    ap.add_argument("--site", required=True, help="this laptop's id in config/fleet.yaml")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--calibrate", action="store_true")
    # a laptop's battery reading can take about a minute to follow a change (config/fleet.yaml meter_lag_s)
    ap.add_argument("--window-s", type=float, default=120.0)
    ap.add_argument("--warmup-s", type=float, default=75.0)
    ap.add_argument("--failsafe-s", type=float, default=10.0)
    ap.add_argument("--token", default=None, help="the Mac's FLEET_TOKEN, if it set one (or BROWNOUT_FLEET_TOKEN)")
    args = ap.parse_args(argv)
    global TOKEN
    TOKEN = args.token or TOKEN
    args.mac = args.mac.rstrip("/")
    meter, job = BatteryMeter(), CompressJob(args.site, args.threads)
    try:
        return calibrate(args, meter, job) if args.calibrate else run(args, meter, job)
    except KeyboardInterrupt:
        print("\nstopping")
        return 0
    finally:
        job.running.clear()
        job.save()
        meter.stop()


if __name__ == "__main__":
    sys.exit(main())
