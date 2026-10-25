"""Griddy Verifier (team/2-anuraag.md FA4): an independent meter check. Grid Desk asks it whether a cap held; it reads
the measured `power` rows straight from runs/<id>/timeline.jsonl on disk, with the standard library only, and runs
no runtime code and uses no dispatcher number. The math is the reporter's (agent/reporter.py), which `make verify`
uses on every committed evidence run:

  - baseline: the mean measured W in the 60 s before the cap starts;
  - window: from the cap's start to its end, cut where it was withdrawn or at the last power sample;
  - time to compliance: seconds from the start to the first sample whose trailing 10-s mean (every sample in that
    span, including ones before the window) is at or under the cap;
  - share under the cap: the fraction of measured samples in the window at or under it.

No power rows means "not measured" and no number. It answers only Grid Desk's address."""
from __future__ import annotations

import gzip
import json
import os
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):                         # `python fetch_agents/verifier.py` from make fetch-three
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_agents.common import NAMES, PROTOCOL, ROOT, RateLimit, address_of, allowed, connect_on_startup, models  # noqa: E402

NAME = NAMES["verifier"]
RUNS = ROOT / "runs"
BASELINE_S = 60.0         # agent/reporter.py BASELINE_S
ROLLING_S = 10.0          # agent/reporter.py ROLLING_S
_RUN_ID = re.compile(r"^[\w.-]+$")


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v)).timestamp()


def read(path: Path) -> list[dict]:
    """The timeline's rows in the order logged; a torn last line (a run mid-write) is skipped."""
    raw = gzip.decompress(path.read_bytes()).decode("utf-8") if path.suffix == ".gz" else path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
    return out


def timeline_of(run_id: str, runs: Path = RUNS) -> Path | None:
    if not _RUN_ID.match(run_id or ""):
        return None
    for name in ("timeline.jsonl", "timeline.jsonl.gz"):
        p = runs / run_id / name
        if p.is_file():
            return p
    return None


def _is_cap(row: dict) -> bool:
    d = row.get("data") or {}
    return row.get("kind") == "event" and "intake" not in d and d.get("start") is not None \
        and d.get("duration_s") is not None and d.get("target_w") is not None


def find(cap_id: str | None, run_id: str | None, runs: Path = RUNS) -> Path | None:
    """The run's timeline: the one named, else the newest run that logged this cap (by id), else the newest run."""
    if run_id:
        return timeline_of(run_id, runs)
    if not runs.is_dir():
        return None
    paths = sorted((p for d in runs.iterdir() if d.is_dir() for p in [timeline_of(d.name, runs)] if p),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if cap_id:
        for p in paths:
            if any(_is_cap(r) and r["data"].get("id") == cap_id for r in read(p)):
                return p
        return None
    return paths[0] if paths else None


def measure(path: Path, cap_id: str | None = None, target_w: float | None = None) -> dict:
    """The verdict's numbers for one run, from its timeline alone. The cap is the one with `cap_id`, else the run's
    first cap (the reporter's choice); `target_w` overrides its watts only when the timeline logged none."""
    rows = read(path)
    fleet = {float(r["data"]["t"]): float(r["data"]["combined_w"]) for r in rows
             if r.get("kind") == "fleet_power" and (r.get("data") or {}).get("combined_w") is not None}
    power = sorted((float(r["data"].get("t", r["t"])), float(r["data"]["combined_w"])) for r in rows
                   if r.get("kind") == "power" and (r.get("data") or {}).get("combined_w") is not None)
    if fleet:                                         # the laptops' watts count against the cap (agent/reporter.py)
        power = sorted((t, fleet.get(t, w)) for t, w in power)
    caps = [r for r in rows if _is_cap(r)]
    cap = next((c for c in caps if c["data"].get("id") == cap_id), None) if cap_id else (caps[0] if caps else None)
    out = {"file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), "run_id": path.parent.name,
           "measured": False, "samples": 0}
    if cap is None:
        return {**out, "note": f"no cap {cap_id} in this run's timeline" if cap_id else "no cap in this run's timeline"}
    d = cap["data"]
    cap_w = float(d["target_w"]) if d.get("target_w") is not None else target_w
    start = _ts(d["start"])
    out.update(cap_id=d.get("id"), target_w=cap_w)
    if not power or start > power[-1][0]:
        return {**out, "window_start": start, "note": "no power rows since the cap started: not measured"}
    end = start + float(d["duration_s"])
    withdrawn = [float(r["t"]) for r in rows if r.get("kind") == "note" and (r.get("data") or {}).get("cap_withdrawn") == d.get("id")]
    end = min([end] + withdrawn + [power[-1][0]])
    window = [(t, w) for t, w in power if start <= t <= end]
    before = [w for t, w in power if start - BASELINE_S <= t < start]
    out.update(window_start=start, window_end=end, samples=len(window), measured=bool(window),
               baseline_w=statistics.fmean(before) if before else None,
               mean_w=statistics.fmean(w for _, w in window) if window else None,
               under_cap_pct=100 * sum(w <= cap_w for _, w in window) / len(window) if window and cap_w is not None else None,
               time_to_compliance_s=compliance(power, start, end, cap_w) if cap_w is not None else None)
    if not window:
        out["note"] = "no power rows in the window: not measured"
    return out


def compliance(power: list[tuple[float, float]], start: float, end: float, cap: float) -> float | None:
    """agent/reporter.time_to_compliance on (t, W) pairs."""
    s = [(t, w) for t, w in power if start - ROLLING_S < t <= end]
    lo, total = 0, 0.0
    for i, (t, w) in enumerate(s):
        total += w
        while s[lo][0] <= t - ROLLING_S:
            total -= s[lo][1]
            lo += 1
        if t >= start and total / (i + 1 - lo) <= cap:
            return t - start
    return None


class Verifier:
    """The decisions, without uagents: who may ask, and the verdict for one VerifyRequest."""

    def __init__(self, M, desk: str | None, runs: Path = RUNS):
        self.M, self.desk, self.runs, self.limit = M, desk, runs, RateLimit(n=30, per_s=60)

    def on_verify(self, sender: str, req, now: float | None = None):
        """The Verdict to send back, or None: a sender that is not Grid Desk is dropped."""
        if not allowed(sender, {self.desk}) or not self.limit.allow(sender, now):
            return None
        path = find(req.cap_id, req.run_id, self.runs)
        if path is None:
            return self.M.Verdict(request_id=req.request_id, measured=False, run_id=req.run_id, cap_id=req.cap_id,
                                  note="no run timeline found for this cap: not measured")
        return self.M.Verdict(request_id=req.request_id, **measure(path, req.cap_id, req.target_w))


# ---------------------------------------------------------------------------------------------- the uAgent
def main() -> int:
    from dotenv import load_dotenv
    from uagents import Agent, Context, Model, Protocol
    import uagents.asgi

    load_dotenv(ROOT / ".env")
    seed, key = os.getenv("FETCH_VERIFIER_SEED", "").strip(), os.getenv("AGENTVERSE_API_KEY", "").strip()
    if not seed:
        print("FETCH_VERIFIER_SEED is empty in .env (docs/judging/fetch-three-agents.md, setup).", file=sys.stderr)
        return 2
    M, desk = models(Model), address_of("grid_desk")
    uagents.asgi.HOST = "127.0.0.1"                   # mailbox mode needs no inbound connection
    about = "Independent meter check: reads measured watts from the run's timeline on disk."
    agent = Agent(name=NAME, seed=seed, port=int(os.getenv("FETCH_VERIFIER_PORT", "8004")), mailbox=True,
                  description=about)
    proto = Protocol(name=PROTOCOL[0], version=PROTOCOL[1])
    brain = Verifier(M, desk)

    @proto.on_message(M.VerifyRequest, replies=M.Verdict)
    async def on_verify(ctx: Context, sender: str, msg):
        verdict = brain.on_verify(sender, msg)
        if verdict is None:
            ctx.logger.warning(f"dropped a VerifyRequest from {sender[:16]}...: not Grid Desk, or over the rate limit")
            return
        ctx.logger.info(f"verdict for {msg.request_id}: measured={verdict.measured} run={verdict.run_id}")
        await ctx.send(sender, verdict)

    agent.include(proto, publish_manifest=True)
    connect_on_startup(agent, seed, key, NAME, about)
    print(f"{NAME} address: {agent.address}; answers only Grid Desk ({desk or 'not configured: set FETCH_GRID_DESK_SEED'})")
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
