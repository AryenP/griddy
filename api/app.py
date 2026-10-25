"""Griddy runtime (built as Brownout): grid watcher + powermetrics + workloads + executor + API/WebSocket.

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
from fleet.hub import Fleet
from replay.engine import Replay
from replay.whatif import WhatIf
from grid.watcher import GridWatcher
from meter.powermetrics import PowerMeter

from .agent_bridge import AgentBridge
from .routes import WEB, make_router
from .ws import Broadcaster

log = logging.getLogger("api.app")


class Runtime:
    def __init__(self, policy_name: str = "dispatcher"):
        dispatcher_enabled = policy_name not in ("baseline", "pause_all")
        self.policy_name = policy_name
        self.tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + ("" if dispatcher_enabled else f"-{policy_name}"))
        self.cal = load_calibration()
        self.meter = PowerMeter(self.tl)
        self.knobs = Knobs(self.tl)
        self.executor = Executor(self.tl, self.knobs, self.cal, load_policy(), dispatcher_enabled,
                                 baseline_mode=policy_name if not dispatcher_enabled else "baseline")
        self.fleet = Fleet(self.tl)                   # laptops that join as measured sites (config/fleet.yaml)
        self.executor.fleet = self.fleet
        self.meter.subscribers.append(lambda r: self.executor.on_power(self.fleet.combine(r)))
        self.replay = Replay(self.tl, self.executor)         # real grid emergencies, replayed through the live software
        self.whatif = WhatIf(self.tl, self.executor, self.replay, (config.events or {}).get("whatif"))   # a judge breaks a part
        self.scale: dict | None = None                               # ERCOT-scale ESTIMATE (grid/scale.py)
        self.agent = AgentBridge(self.tl, self.executor)
        self.agent.snapshot = self.snapshot
        self.watcher: GridWatcher | None = None
        self.watcher_task: asyncio.Task | None = None
        self.broadcaster: Broadcaster | None = None
        self._tasks: list[asyncio.Task] = []
        self._cap_lock = asyncio.Lock()                       # cuts reach the dispatcher one batch at a time

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

    async def switch_iso(self, iso: str, who: str = ""):
        loc = config.isos["isos"][iso]["locations"]
        location = settings.location if iso == settings.iso else (loc[0] if isinstance(loc, list) else loc)
        self.tl.log("policy", reason="iso change", iso=iso, location=location, who=who)
        return await self._start_watcher(iso, location)

    async def start(self):
        import telemetry
        self.telemetry = telemetry.configure()      # OpenTelemetry; Application Insights when configured
        self.broadcaster = Broadcaster(self.tl, asyncio.get_running_loop())
        self.tl.log("note", msg="runtime start", dispatcher_enabled=self.executor.dispatcher_enabled,
                    policy=self.policy_name,
                    calibration_measured_at=self.cal.measured_at, machine=self.cal.machine,
                    agent=self.agent.status, agent_model=self.agent.llm.name, telemetry=self.telemetry)
        await self.meter.start()
        self.knobs.set_concurrency("chat", next(j["max_concurrency"] for j in config.jobs["jobs"] if j["id"] == "chat"))
        for j in ("chat", "train", "batch"):
            self.knobs.start(j, paused=True)
        await self._start_watcher(settings.iso, settings.location)
        self._tasks.append(asyncio.create_task(self.executor.run()))
        if self.replay.enabled:
            self._tasks.append(asyncio.create_task(self._replay_loop()))
        if config.site.get("scale"):
            self._tasks.append(asyncio.create_task(self._scale_loop(config.site["scale"])))

    async def _replay_loop(self):
        """Once a second: the replayed event's real data, and its alerts to the real dispatcher as they fall due."""
        while True:
            try:
                self.replay.tick()
                self.whatif.tick()
                gone, self.replay.pending_withdraw = self.replay.pending_withdraw, []
                new, self.replay.pending_caps = self.replay.pending_caps, []
                if gone or new:                     # a re-plan takes seconds: the replayed clock keeps ticking meanwhile
                    self._tasks.append(asyncio.create_task(self._hand_over(gone, new)))
                    self._tasks = [t for t in self._tasks if not t.done()]
            except Exception as e:                  # the replay never stops the real loop
                log.exception("replay tick failed")
                self.tl.log("note", level="error", msg=f"replay tick failed: {e!r}"[:300])
            await asyncio.sleep(1.0)

    async def _hand_over(self, gone: list[str], new: list):
        """Withdrawn cuts, then new ones, to the real dispatcher, one batch at a time and in order."""
        async with self._cap_lock:
            try:
                for cap_id in gone:
                    await self.executor.remove_event(cap_id, "the alert or what-if ended, or the replay stopped")
                for ev in new:
                    await self.executor.add_event(ev)
            except Exception as e:
                log.exception("handing a cut to the dispatcher failed")
                self.tl.log("note", level="error", msg=f"cut hand-over failed: {e!r}"[:300])

    async def _scale_loop(self, cfg: dict):
        """Every `poll_s`: ERCOT's live demand, and what this Mac's measured cut would mean there (an estimate)."""
        from grid import isos, scale
        while True:
            try:
                cond = await asyncio.to_thread(isos.fetch_ercot_conditions)
                self.scale = scale.estimate(cfg, cond.get("Actual System Demand"), cond.get("Time"))
                self.tl.log("scale", **self.scale)
            except Exception as e:                  # feed down: keep the last estimate, say so in the log
                log.warning("ERCOT demand fetch failed: %r", e)
                self.tl.log("note", level="warning", feed="ercot_scale", error=repr(e)[:300])
            await asyncio.sleep(float(cfg.get("poll_s", 300)))

    async def stop(self):
        for t in self._tasks + ([self.watcher_task] if self.watcher_task else []):
            t.cancel()
        await asyncio.to_thread(self.knobs.stop_all)
        if self.meter._proc is not None:
            await self.meter.stop()
        import telemetry
        await asyncio.to_thread(telemetry.flush)
        self.tl.log("note", msg="runtime stop")
        self.tl.close()

    def snapshot(self) -> dict:
        ex = self.executor
        dump = lambda m: m.model_dump(mode="json") if m is not None else None
        return {"grid": dump(ex.signal), "schedule": dump(ex.schedule), "plan": dump(ex.plan),
                "power": dump(self.meter.latest), "power_history": [[round(t, 2), round(w, 3)] for t, w in ex.power],
                "jobs": {j: Knobs.status(j) for j in ("chat", "train", "batch")},
                "calibration": dump(ex.cal), "fleet": self.fleet.status(), "replay": self.replay.summary(), "whatif": self.whatif.last, "scale": self.scale, "policy": dump(ex.policy), "iso_options": available_isos(),
                "iso": self.watcher.iso if self.watcher else settings.iso,
                "dispatcher_enabled": ex.dispatcher_enabled, "agent": self.agent.status, "agent_model": self.agent.llm.name,
                "approvals": [dump(x) for x in self.agent.pending(status=None)],
                "cap_events": [dump(e) for e in ex.active_events()],
                "explanation": dump(self.agent.explanation), "run_id": self.tl.run_id,
                "job_specs": {j.id: j.model_dump(mode="json") for j in ex.jobs()},
                "quote": config.site.get("quote")}


class FreshFiles(StaticFiles):
    """The pages, always revalidated (ETag): without a Cache-Control header browsers kept an hours-old page and
    stylesheet on Aryen's screen (Sat 19:07). On loopback the check costs nothing."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def make_app(rt: Runtime) -> FastAPI:
    app = FastAPI(title="Griddy")
    app.include_router(make_router(rt))
    if Path(WEB).is_dir():
        app.mount("/", FreshFiles(directory=WEB, html=True), name="web")
    return app


class _Server(uvicorn.Server):
    """uvicorn without its own signal capture: the runtime owns SIGINT/SIGTERM so shutdown always
    runs (checkpoint training, stop workloads, stop the meter, close the timeline)."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def scripted_inputs(rt: "Runtime", args) -> None:
    """For headless evidence runs (`make evidence`): the same inputs in dispatched and baseline runs, so the
    comparison covers the same window and the same request. Logged like any operator input."""
    from datetime import datetime, timedelta

    from core.types import CapEvent
    for spec in args.deadline or []:
        job, hours = spec.split("=")
        await rt.executor.set_job(job, deadline=datetime.now().astimezone() + timedelta(hours=float(hours)))
    if args.cap_pct is None and args.cap_w is None:
        return
    await asyncio.sleep(args.cap_at)
    ev = CapEvent(source="ui", start=datetime.now().astimezone(), duration_s=args.cap_for, target_pct=args.cap_pct,
                  target_w=args.cap_w, reason="scripted cap for the evidence run", raw=" ".join(map(str, vars(args).items())))
    await rt.executor.add_event(ev)


async def chat_load(rt: "Runtime", args) -> None:
    """Headless: real chat requests to the real model through the chat proxy, `--chat-load` streams from
    `--chat-at` s, so a run records chat's time to first token while a cap is in force. The prompts are the
    calibration prompts in config/jobs.yaml; the timeline says this traffic was scripted."""
    from controller.feasibility import chat_traffic
    await asyncio.sleep(args.chat_at)
    gap = f", each waiting {args.chat_gap:g} s after a reply" if args.chat_gap else ", back to back"
    rt.tl.log("note", msg=f"scripted chat traffic: {args.chat_load} stream(s) of real requests to the real model{gap} "
                          f"(prompts: config/jobs.yaml calibration_prompts)", trigger="scripted_chat",
              streams=args.chat_load, gap_s=args.chat_gap)
    await chat_traffic(asyncio.Event(), args.chat_load, args.chat_gap)


async def amain(args):
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    rt = Runtime(policy_name=settings.policy_name)
    try:
        await rt.start()
        print(f"run {rt.tl.run_id}: timeline {rt.tl.path}", flush=True)
        if args.headless:
            scripted = asyncio.create_task(scripted_inputs(rt, args))
            chat = asyncio.create_task(chat_load(rt, args)) if args.chat_load else None
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=args.duration)
            scripted.cancel()
            if chat:
                chat.cancel()
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
    ap.add_argument("--deadline", action="append", metavar="JOB=HOURS", help="headless: set a job's deadline N h from now")
    ap.add_argument("--cap-pct", type=float, help="headless: cut this %% below the measured 60-s baseline")
    ap.add_argument("--cap-w", type=float, help="headless: cap machine power at this many watts")
    ap.add_argument("--cap-at", type=int, default=120, help="headless: seconds after start (>= 70 for a %% cap)")
    ap.add_argument("--cap-for", type=int, default=300, help="headless: cap duration in seconds")
    ap.add_argument("--chat-load", type=int, default=0, help="headless: scripted real chat requests, this many streams")
    ap.add_argument("--chat-at", type=int, default=30, help="headless: seconds after start the chat traffic begins")
    ap.add_argument("--chat-gap", type=float, default=0.0, help="headless: seconds each stream waits after a reply")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(amain(ap.parse_args()))
