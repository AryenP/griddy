"""Brownout runtime: grid watcher + powermetrics + workloads + executor + API/WebSocket.

    sudo -v && make demo                         # live, dashboard on HOST:PORT
    sudo -v && POLICY=baseline make baseline      # dispatcher off, headless, fixed duration
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from controller.execute import Executor
from controller.knobs import Knobs
from core import config
from core.config import available_isos, settings
from core.timeline import Timeline
from dispatcher.solve import load_calibration, load_policy
from grid.watcher import GridWatcher
from meter.powermetrics import PowerMeter

from .agent_bridge import AgentBridge
from .routes import WEB, make_router
from .ws import Broadcaster

log = logging.getLogger("api.app")


class Runtime:
    def __init__(self, dispatcher_enabled: bool):
        self.tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + ("" if dispatcher_enabled else "-baseline"))
        self.cal = load_calibration()
        self.meter = PowerMeter(self.tl)
        self.knobs = Knobs(self.tl)
        self.executor = Executor(self.tl, self.knobs, self.cal, load_policy(), dispatcher_enabled)
        self.meter.subscribers.append(self.executor.on_power)
        self.agent = AgentBridge(self.tl, self.executor)
        self.watcher: GridWatcher | None = None
        self.watcher_task: asyncio.Task | None = None
        self.broadcaster: Broadcaster | None = None
        self._tasks: list[asyncio.Task] = []

    def _on_signal(self, sig):
        self._tasks.append(asyncio.get_running_loop().create_task(self.executor.on_signal(sig)))
        self._tasks = [t for t in self._tasks if not t.done()]

    async def _start_watcher(self, iso: str, location: str):
        if self.watcher_task:
            self.watcher_task.cancel()
        self.watcher = GridWatcher(iso, location, self.tl)
        self.watcher.subscribers.append(self._on_signal)
        self.watcher_task = asyncio.create_task(self.watcher.run())
        for _ in range(600):                        # first pull of every feed (CAISO ~10 s, ERCOT longer)
            if self.watcher.latest is not None:
                return self.watcher.latest
            if self.watcher_task.done():
                self.watcher_task.result()          # surface the failure
            await asyncio.sleep(0.25)
        raise TimeoutError(f"no {iso} signal after 150 s")

    async def switch_iso(self, iso: str):
        loc = config.isos["isos"][iso]["locations"]
        location = settings.location if iso == settings.iso else (loc[0] if isinstance(loc, list) else loc)
        self.tl.log("policy", reason="iso change", iso=iso, location=location)
        return await self._start_watcher(iso, location)

    async def start(self):
        self.broadcaster = Broadcaster(self.tl, asyncio.get_running_loop())
        self.tl.log("note", msg="runtime start", dispatcher_enabled=self.executor.dispatcher_enabled,
                    calibration_measured_at=self.cal.measured_at, machine=self.cal.machine,
                    agent=self.agent.status, agent_model=self.agent.llm.name)
        await self.meter.start()
        self.knobs.set_concurrency("chat", next(j["max_concurrency"] for j in config.jobs["jobs"] if j["id"] == "chat"))
        for j in ("chat", "train", "batch"):
            self.knobs.start(j, paused=True)
        await self._start_watcher(settings.iso, settings.location)
        self._tasks.append(asyncio.create_task(self.executor.run()))

    async def stop(self):
        for t in self._tasks + ([self.watcher_task] if self.watcher_task else []):
            t.cancel()
        await asyncio.to_thread(self.knobs.stop_all)
        if self.meter._proc is not None:
            await self.meter.stop()
        self.tl.log("note", msg="runtime stop")
        self.tl.close()

    def snapshot(self) -> dict:
        ex = self.executor
        dump = lambda m: m.model_dump(mode="json") if m is not None else None
        return {"grid": dump(ex.signal), "schedule": dump(ex.schedule), "plan": dump(ex.plan),
                "power": dump(self.meter.latest), "jobs": {j: Knobs.status(j) for j in ("chat", "train", "batch")},
                "calibration": dump(self.cal), "policy": dump(ex.policy), "iso_options": available_isos(),
                "iso": self.watcher.iso if self.watcher else settings.iso,
                "dispatcher_enabled": ex.dispatcher_enabled, "agent": self.agent.status, "agent_model": self.agent.llm.name,
                "approvals": [dump(x) for x in self.agent.pending(status=None)],
                "explanation": dump(self.agent.explanation), "run_id": self.tl.run_id,
                "job_specs": {j.id: j.model_dump(mode="json") for j in ex.jobs()},
                "quote": config.site.get("quote")}


def make_app(rt: Runtime) -> FastAPI:
    app = FastAPI(title="Brownout")
    app.include_router(make_router(rt))
    if Path(WEB).is_dir():
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app


class _Server(uvicorn.Server):
    """uvicorn without its own signal capture: the runtime owns SIGINT/SIGTERM so shutdown always
    runs (checkpoint training, stop workloads, stop the meter, close the timeline)."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def amain(args):
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    rt = Runtime(dispatcher_enabled=settings.policy_name != "baseline")
    try:
        await rt.start()
        print(f"run {rt.tl.run_id}: timeline {rt.tl.path}", flush=True)
        if args.headless:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=args.duration)
        else:
            server = _Server(uvicorn.Config(make_app(rt), host=settings.host, port=settings.port, log_level="warning"))
            serving = asyncio.create_task(server.serve())
            print(f"dashboard http://localhost:{settings.port}  phone {settings.public_url}", flush=True)
            await asyncio.wait([serving, asyncio.create_task(stop.wait())], return_when=asyncio.FIRST_COMPLETED)
            server.should_exit = True
            await serving
    finally:
        print("stopping: checkpointing workloads, stopping meter", flush=True)
        await rt.stop()
        print(f"stopped; timeline {rt.tl.path}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--duration", type=int, default=600)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(amain(ap.parse_args()))
