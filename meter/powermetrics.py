"""SoC power measured by macOS: `sudo powermetrics --samplers cpu_power,gpu_power -i 1000`.
Independent of our code. Parsed at 1 Hz into PowerReading and logged as `power` events.
Attribution per job is NOT done here; that comes from calibration deltas and is labelled so.

    uv run python -m meter.powermetrics --seconds 5     # print readings (needs sudo -v first)
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time

from core.timeline import Timeline
from core.types import PowerReading

_LINE = re.compile(r"^(CPU|GPU|ANE|Combined) Power(?: \([^)]*\))?:\s*(\d+(?:\.\d+)?)\s*mW", re.M)
_HEADER = "*** Sampled system activity"
SAMPLERS = "cpu_power,gpu_power"


def parse_sample(text: str) -> dict[str, float]:
    """Watts by field from one powermetrics sample block. Fields present depend on the machine;
    `make probe` prints which ones this Mac has."""
    return {m.group(1).lower(): float(m.group(2)) / 1000.0 for m in _LINE.finditer(text)}


def reading_from(fields: dict[str, float], t: float | None = None) -> PowerReading:
    if "combined" in fields:
        combined = fields["combined"]
    else:
        combined = sum(v for k, v in fields.items() if k in ("cpu", "gpu", "ane"))
    return PowerReading(t=t or time.time(), cpu_w=fields.get("cpu"), gpu_w=fields.get("gpu"),
                        ane_w=fields.get("ane"), combined_w=combined, fields=sorted(fields))


class PowerMeter:
    def __init__(self, timeline: Timeline | None = None, interval_ms: int = 1000):
        self.tl, self.interval_ms = timeline, interval_ms
        self.latest: PowerReading | None = None
        self.subscribers: list = []
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None

    async def start(self):
        # `sudo -n`: never prompt from inside the app; fail fast with a clear message instead.
        self._proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "powermetrics", "--samplers", SAMPLERS, "-i", str(self.interval_ms),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._task = asyncio.create_task(self._read())
        # give it a moment to fail if sudo has no cached credential
        await asyncio.sleep(0.5)
        if self._proc.returncode is not None:
            err = (await self._proc.stderr.read()).decode(errors="replace").strip()
            raise RuntimeError(f"powermetrics exited {self._proc.returncode}: {err or 'run `sudo -v` first'}")

    async def _read(self):
        buf: list[str] = []
        assert self._proc and self._proc.stdout
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace")
            # A sample runs from one header to the next. On macOS 15 the GPU section repeats
            # "GPU Power" after "Combined Power", so never split a sample on the Combined line.
            if line.startswith(_HEADER) and buf:
                self._emit("".join(buf)); buf = []
            buf.append(line)
        if buf:
            self._emit("".join(buf))

    def _emit(self, block: str):
        fields = parse_sample(block)
        if "combined" not in fields and not {"cpu", "gpu"} <= set(fields):
            return   # partial block, not a full sample
        r = reading_from(fields)
        self.latest = r
        if self.tl:
            self.tl.log("power", source="powermetrics", **r.model_dump(exclude={"source"}))
        for cb in list(self.subscribers):
            cb(r)

    async def stop(self):
        if self._task:
            self._task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 3)
            except asyncio.TimeoutError:
                self._proc.kill()


async def _main(seconds: int):
    m = PowerMeter()
    m.subscribers.append(lambda r: print(
        f"{time.strftime('%H:%M:%S', time.localtime(r.t))}  combined {r.combined_w:6.2f} W   "
        f"cpu {r.cpu_w or 0:6.2f}  gpu {r.gpu_w or 0:6.2f}  ane {r.ane_w or 0:5.2f}   fields={r.fields}"))
    await m.start()
    await asyncio.sleep(seconds)
    await m.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=5)
    asyncio.run(_main(ap.parse_args().seconds))
