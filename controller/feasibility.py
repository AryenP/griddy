"""Measured feasibility inputs (SPEC §6): idle floor and per-job watt deltas, from powermetrics.

    sudo -v && make calibrate     # writes runs/calibration.json and a timeline

Each phase: start the job (or chat traffic at max concurrency), wait warmup_s, average
`Combined Power` over window_s, subtract the idle floor. Rates (steps/s, items/s) come from
the workloads' own status files over the same window.
"""
from __future__ import annotations

import argparse
import asyncio
import platform
import statistics
import subprocess
import time
from pathlib import Path

import httpx

from core import config
from core.timeline import Timeline
from core.types import Calibration, DevicePower
from meter.powermetrics import PowerMeter
from workloads.base import WL

from .knobs import Knobs

CAL = WL.get("calibration", {})
CHAT = WL.get("chat", {})


def machine() -> str:
    try:
        chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    except OSError:
        chip = platform.machine()
    return f"{chip} macOS {platform.mac_ver()[0]}"


class Window:
    def __init__(self, meter: PowerMeter):
        self.meter, self.samples, self.on = meter, [], False
        meter.subscribers.append(self._cb)

    def _cb(self, r):
        if self.on:
            self.samples.append(r.combined_w)

    async def measure(self, seconds: float) -> tuple[float, int]:
        self.samples, self.on = [], True
        await asyncio.sleep(seconds)
        self.on = False
        if len(self.samples) < max(3, seconds // 2):
            raise RuntimeError(f"only {len(self.samples)} powermetrics samples in {seconds}s")
        return statistics.fmean(self.samples), len(self.samples)


async def chat_traffic(stop: asyncio.Event, n: int):
    prompts = CHAT["calibration_prompts"]
    url = f"http://127.0.0.1:{CHAT['proxy_port']}/chat"
    async with httpx.AsyncClient(timeout=120) as c:
        async def worker(k):
            i = k
            while not stop.is_set():
                await c.post(url, json={"messages": [{"role": "user", "content": prompts[i % len(prompts)]}]})
                i += n
        await asyncio.gather(*(worker(k) for k in range(n)))


async def calibrate(out: Path, only: list[str]) -> Calibration:
    tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + "-calibrate")
    meter = PowerMeter(tl)
    await meter.start()
    win = Window(meter)
    knobs = Knobs(tl)
    w, warm, cool = CAL["window_s"], CAL["warmup_s"], CAL["cooldown_s"]
    jobs_cfg = {j["id"]: j for j in config.jobs["jobs"]}
    result: dict[str, dict[str, DevicePower]] = {}

    def say(msg, **kw):
        print(msg, flush=True)
        tl.log("note", phase="calibrate", msg=msg, **kw)

    try:
        for j in only:
            knobs.start(j, paused=True)
        if "chat" in only:
            knobs.set_concurrency("chat", jobs_cfg["chat"]["max_concurrency"])
            async with httpx.AsyncClient() as c:      # proxy up?
                for _ in range(60):
                    try:
                        (await c.get(f"http://127.0.0.1:{CHAT['proxy_port']}/status")).raise_for_status(); break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.5)
                await c.post(f"http://127.0.0.1:{CHAT['proxy_port']}/chat", timeout=180,
                             json={"messages": [{"role": "user", "content": "hi"}]})   # load the model
        # warm every model once so loading is not inside a window
        for j in [j for j in ("train", "batch") if j in only]:
            knobs.set_device(j, "gpu"); knobs.run(j)
            await asyncio.to_thread(knobs.wait_for, j, lambda s: s.get("state") == "running", 180)
            knobs.pause(j)
            await asyncio.to_thread(knobs.wait_for, j, lambda s: s.get("state") == "paused", 60)

        await asyncio.sleep(cool)
        idle, n = await win.measure(w)
        say(f"idle floor            {idle:6.2f} W  ({n} samples)", idle_w=idle)

        if "chat" in only:   # chat at max concurrency
            conc = jobs_cfg["chat"]["max_concurrency"]
            stop = asyncio.Event()
            task = asyncio.create_task(chat_traffic(stop, conc))
            await asyncio.sleep(warm)
            mean, n = await win.measure(w)
            stop.set(); await task
            st = Knobs.status("chat")
            result["chat"] = {"gpu": DevicePower(delta_w=max(0.0, mean - idle), concurrency=conc, samples=n)}
            say(f"chat  gpu  conc={conc}   {mean:6.2f} W  delta {mean - idle:+6.2f} W  p95 {st.get('p95_60s')} s",
                job="chat", device="gpu", mean_w=mean, delta_w=mean - idle, p95_s=st.get("p95_60s"))
            await asyncio.sleep(cool)

        for j in [j for j in ("train", "batch") if j in only]:
            devs = ["gpu", "cpu"] if jobs_cfg[j]["device"] == "either" else [jobs_cfg[j]["device"]]
            result[j] = {}
            for d in devs:
                knobs.set_device(j, d); knobs.run(j)
                await asyncio.to_thread(knobs.wait_for, j, lambda s, d=d: s.get("state") == "running" and s.get("device") == d, 180)
                await asyncio.sleep(warm)
                mean, n = await win.measure(w)
                rate = Knobs.status(j).get("rate")
                knobs.pause(j)
                result[j][d] = DevicePower(delta_w=max(0.0, mean - idle), rate=rate, samples=n)
                say(f"{j:<5} {d}             {mean:6.2f} W  delta {mean - idle:+6.2f} W  rate {rate} {Knobs.status(j).get('rate_unit')}",
                    job=j, device=d, mean_w=mean, delta_w=mean - idle, rate=rate)
                await asyncio.to_thread(knobs.wait_for, j, lambda s: s.get("state") == "paused", 60)
                await asyncio.sleep(cool)
    finally:
        knobs.stop_all()
        await meter.stop()

    # merge into an existing calibration so jobs can be measured in separate sessions
    if out.exists():
        prev = Calibration.model_validate_json(out.read_text())
        result = {**prev.jobs, **result}
    cal = Calibration(measured_at=time.time(), machine=machine(), idle_w=idle, window_s=w, jobs=result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cal.model_dump_json(indent=2))
    tl.log("note", phase="calibrate", msg="calibration written", path=str(out), calibration=cal.model_dump(mode="json"))
    tl.close()
    print(f"\ncalibration: {out}\ntimeline:    {tl.path}")
    return cal


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true", required=True)
    ap.add_argument("--out", default=config.settings.calibration_path)
    ap.add_argument("--only", default="chat,train,batch", help="comma list of jobs to measure")
    a = ap.parse_args()
    asyncio.run(calibrate(Path(a.out), [j.strip() for j in a.only.split(",") if j.strip()]))
