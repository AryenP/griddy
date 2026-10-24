"""Measured feasibility inputs (SPEC §6): idle floor and per-job watt deltas, from powermetrics.

    sudo -v && make calibrate     # writes runs/calibration.json and a timeline
    make chat-sweep               # chat latency (TTFT and total) by concurrency x max_tokens, no sudo

Each phase: start the job (or chat traffic at each of `chat_streams` busy streams), wait warmup_s, average
`Combined Power` over window_s, subtract the idle floor. Rates (steps/s, items/s) come from
the workloads' own status files over the same window.
"""
from __future__ import annotations

import argparse
import asyncio
import json
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


async def chat_traffic(stop: asyncio.Event, n: int, gap_s: float = 0.0):
    """`n` users sending the calibration prompts; each waits `gap_s` after a reply before its next request
    (0: back to back, as calibration needs; a pause to read is what a judge on a phone does)."""
    prompts = CHAT["calibration_prompts"]
    url = f"http://127.0.0.1:{CHAT['proxy_port']}/chat"
    async with httpx.AsyncClient(timeout=120) as c:
        async def worker(k):
            i = k
            while not stop.is_set():
                await c.post(url, json={"messages": [{"role": "user", "content": prompts[i % len(prompts)]}]})
                i += n
                if gap_s:
                    await asyncio.sleep(gap_s)
        await asyncio.gather(*(worker(k) for k in range(n)))


async def calibrate(out: Path, only: list[str]) -> Calibration:
    tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + "-calibrate")
    meter = PowerMeter(tl)
    await meter.start()
    win = Window(meter)
    # measure on scratch state: the demo's backlog (train steps, batch items) is not consumed
    knobs = Knobs(tl, env={"BROWNOUT_CHECKPOINT_DIR": str(tl.dir / "checkpoints")})
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

        if "chat" in only:   # chat at each measured load, concurrency at max so every stream is served at once
            conc = jobs_cfg["chat"]["max_concurrency"]
            streams_w = {}
            for k in sorted(set(CAL.get("chat_streams", [conc])) | {conc}):
                stop = asyncio.Event()
                task = asyncio.create_task(chat_traffic(stop, k))
                await asyncio.sleep(warm)
                mean, n = await win.measure(w)
                stop.set(); await task
                st = Knobs.status("chat")
                streams_w[k] = max(0.0, mean - idle)
                say(f"chat  gpu  streams={k}  {mean:6.2f} W  delta {mean - idle:+6.2f} W  p95 {st.get('p95_60s')} s",
                    job="chat", device="gpu", streams=k, mean_w=mean, delta_w=mean - idle, p95_s=st.get("p95_60s"))
                await asyncio.sleep(cool)
            result["chat"] = {"gpu": DevicePower(delta_w=streams_w[conc], concurrency=conc, samples=n,
                                                 streams_w=streams_w)}

        for j in [j for j in ("train", "batch") if j in only]:
            devs = ["gpu", "cpu"] if jobs_cfg[j]["device"] == "either" else [jobs_cfg[j]["device"]]
            result[j] = {}
            for d in devs:
                knobs.set_device(j, d); knobs.run(j)
                await asyncio.to_thread(knobs.wait_for, j, lambda s, d=d: s.get("state") == "running" and s.get("device") == d, 180)
                await asyncio.sleep(warm)
                mean, n = await win.measure(w)
                st = Knobs.status(j)
                if st.get("state") == "done":
                    raise RuntimeError(f"{j} finished its work inside the {w}s window on {d}; the measurement "
                                       "would include idle time. Use a larger corpus or a shorter window.")
                rate = st.get("rate")
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


async def chat_sweep(out: Path, concurrencies: list[int], max_tokens: list[int], requests: int,
                     with_train: bool) -> dict:
    """Closed-loop load: `c` clients each send requests back to back through the proxy at limit `c`.
    Records per-request TTFT and total latency from the proxy's own measurements."""
    from workloads.chat_proxy import p95
    tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + "-chat-sweep")
    knobs = Knobs(tl, env={"BROWNOUT_CHECKPOINT_DIR": str(tl.dir / "checkpoints")})
    url = f"http://127.0.0.1:{CHAT['proxy_port']}/chat"
    rows = []
    try:
        knobs.start("chat")
        if with_train:
            knobs.start("train", paused=True)
            knobs.set_device("train", "gpu"); knobs.run("train")
            await asyncio.to_thread(knobs.wait_for, "train", lambda s: s.get("state") == "running", 180)
        async with httpx.AsyncClient(timeout=300) as c:
            for _ in range(60):
                try:
                    (await c.get(url.replace("/chat", "/status"))).raise_for_status(); break
                except httpx.HTTPError:
                    await asyncio.sleep(0.5)
            await c.post(url, json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8})
            prompts = CHAT["calibration_prompts"]
            for conc in concurrencies:
                knobs.set_concurrency("chat", conc)
                await asyncio.sleep(0.5)
                for mt in max_tokens:
                    res: list[dict] = []

                    async def client(k):
                        for i in range(requests // conc):
                            r = await c.post(url, json={"messages": [{"role": "user", "content": prompts[(k + i) % len(prompts)]}],
                                                        "max_tokens": mt})
                            res.append(r.json())
                    t0 = time.time()
                    await asyncio.gather(*(client(k) for k in range(conc)))
                    wall = time.time() - t0
                    row = {"concurrency": conc, "max_tokens": mt, "n": len(res), "with_train": with_train,
                           "ttft_p95_s": p95([r["ttft_s"] for r in res]), "total_p95_s": p95([r["latency_s"] for r in res]),
                           "tokens_per_s": round(sum(r["tokens"] or 0 for r in res) / wall, 1)}
                    rows.append(row)
                    tl.log("latency", phase="chat-sweep", **row)
                    print(f"conc {conc}  max_tokens {mt:>3}  n {row['n']:>2}  TTFT p95 {row['ttft_p95_s']:6.2f} s  "
                          f"total p95 {row['total_p95_s']:6.2f} s  {row['tokens_per_s']:6.1f} tok/s"
                          + ("  (train on GPU)" if with_train else ""), flush=True)
    finally:
        await asyncio.to_thread(knobs.stop_all)
        tl.close()
    result = {"measured_at": time.time(), "machine": machine(), "model": config.settings.ollama_model, "rows": rows}
    prev = json.loads(out.read_text()) if out.exists() else {"runs": []}
    prev["runs"].append(result)
    out.write_text(json.dumps(prev, indent=2))
    print(f"\nchat sweep: {out}\ntimeline:   {tl.path}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calibrate", action="store_true")
    mode.add_argument("--chat-sweep", action="store_true")
    ap.add_argument("--with-train", action="store_true", help="chat sweep with training on the GPU")
    ap.add_argument("--requests", type=int, default=8, help="chat sweep: requests per setting")
    ap.add_argument("--out", default=config.settings.calibration_path)
    ap.add_argument("--only", default="chat,train,batch", help="comma list of jobs to measure")
    a = ap.parse_args()
    if a.chat_sweep:
        asyncio.run(chat_sweep(Path("runs/chat_sweep.json"), [1, 2, 4], [64, 128, 256], a.requests, a.with_train))
    else:
        asyncio.run(calibrate(Path(a.out), [j.strip() for j in a.only.split(",") if j.strip()]))
