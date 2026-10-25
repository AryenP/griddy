"""Event-window reports and run comparisons from timelines, and nothing else (SPEC §9, CLAUDE.md rule 4).

Every number is computed from the events one run logged (HANDOFF.md):
  power     data.combined_w at data.t (powermetrics, 1 Hz)
  fleet_power  when laptops joined (fleet/hub.py): the same second's total, the Mac plus each laptop's own
            battery reading; it replaces that second's power sample, so the cap is judged on the fleet
  grid      data.feed == "signal": price_now ($/MWh) and carbon_now (gCO2/kWh) in effect from then on
  event     a CapEvent (start, duration_s, target_w; % targets already resolved by the executor).
            The agent bridge also logs `event` with data.intake (the parsed request): not a cap.
  state     data.job == "chat": ttft_p95_60s (the SLA metric) and p95_60s (total latency, reported only)
  approval  ApprovalRequest dumps, and {request_id, who, decision} for each owner reply
  shortfall shortfall_kind + message;  policy  job changes (deadlines);  note  "runtime start"
Watts are measured, prices and carbon are the live values in effect at each second. Nothing is typed in.

    python -m agent.reporter --run <id>|latest     # writes reports/<id>.md and reports/<id>-power.png

API (machine 1): build_report(path) -> Report, compare_runs(dispatched, baseline) -> Comparison,
resolve(run) -> (path, run_id), run_path(run_id) (the API's: run ids only), runtime_runs() / newest(),
run_series(path) -> one run's measured watts, caps, actions and shortfalls for drawing.
"""
from __future__ import annotations

import argparse
import gzip
import bisect
import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from core import config
from core.types import Comparison, Report, TimelineEvent

RUNS = Path("runs")
BASELINE_S = 60.0      # pre-event baseline: mean measured W over this many seconds before the event
ROLLING_S = 10.0       # compliance: the trailing mean over this many seconds must be at or under the cap
MAX_GAP_S = 5.0        # meter gaps longer than this are not integrated (no energy is invented for them)
SLA_KEY = "chat_ttft_p95_s"


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v)).timestamp()


KNOWN_KINDS = set(get_args(TimelineEvent.model_fields["kind"].annotation))


def _read(path: Path) -> list[TimelineEvent]:
    """Timeline events in time order. A live run may be mid-write: a torn last line is skipped. A `.gz` timeline is
    a committed evidence run (docs/evidence/runs/<id>/timeline.jsonl.gz), read as it was logged."""
    text = gzip.decompress(path.read_bytes()).decode("utf-8") if path.suffix == ".gz" else path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        try:
            out.append(TimelineEvent(**json.loads(ln)))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
        except ValidationError:                     # an event kind this version does not log (a run made on another branch)
            if json.loads(ln).get("kind") in KNOWN_KINDS:
                raise
    out.sort(key=lambda e: e.t)
    return out


def is_cap(ev: TimelineEvent) -> bool:
    d = ev.data
    return ev.kind == "event" and "intake" not in d and d.get("start") is not None \
        and d.get("duration_s") is not None and d.get("target_w") is not None


@dataclass
class Run:
    """A timeline split by kind, in time order."""

    run_id: str
    path: Path
    power: list[tuple[float, float]] = field(default_factory=list)      # (t, combined W)
    grid: list[TimelineEvent] = field(default_factory=list)             # feed == "signal" only
    caps: list[TimelineEvent] = field(default_factory=list)
    chat: list[TimelineEvent] = field(default_factory=list)             # state events of the chat job
    states: list[TimelineEvent] = field(default_factory=list)
    approvals: list[TimelineEvent] = field(default_factory=list)
    schedules: list[TimelineEvent] = field(default_factory=list)
    shortfalls: list[TimelineEvent] = field(default_factory=list)
    policies: list[TimelineEvent] = field(default_factory=list)
    actions: list[TimelineEvent] = field(default_factory=list)
    notes: list[TimelineEvent] = field(default_factory=list)            # cap withdrawals, fleet changes
    fleet: dict[float, dict] = field(default_factory=dict)              # t -> {mac_w, sites, combined_w}
    start_note: dict | None = None
    first_t: float | None = None
    last_t: float | None = None
    _grid_t: list[float] = field(default_factory=list, repr=False)

    @classmethod
    def load(cls, path: str | Path, run_id: str | None = None) -> Run:
        path = Path(path)
        r = cls(run_id=run_id or _run_id(path), path=path)
        events = _read(path)
        if events:
            r.first_t, r.last_t = events[0].t, events[-1].t
        for ev in events:
            d = ev.data
            if ev.kind == "fleet_power" and d.get("combined_w") is not None:
                r.fleet[float(d["t"])] = d
            elif ev.kind == "power" and d.get("combined_w") is not None:
                r.power.append((float(d.get("t", ev.t)), float(d["combined_w"])))
            elif ev.kind == "grid" and d.get("feed") == "signal":
                r.grid.append(ev)
            elif is_cap(ev):
                r.caps.append(ev)
            elif ev.kind == "state":
                (r.chat if d.get("job") == "chat" else r.states).append(ev)
            elif ev.kind == "approval":
                r.approvals.append(ev)
            elif ev.kind == "schedule":
                r.schedules.append(ev)
            elif ev.kind == "shortfall":
                r.shortfalls.append(ev)
            elif ev.kind == "policy":
                r.policies.append(ev)
            elif ev.kind == "action":
                r.actions.append(ev)
            elif ev.kind == "note" and (d.get("cap_withdrawn") or d.get("trigger") in ("fleet", "background")):
                r.notes.append(ev)
            elif ev.kind == "note" and d.get("msg") == "runtime start" and r.start_note is None:
                r.start_note = {"t": ev.t, **d}
        if r.fleet:
            r.power = [(t, float(r.fleet[t]["combined_w"]) if t in r.fleet else w) for t, w in r.power]
        r.power.sort()
        r._grid_t = [g.t for g in r.grid]
        return r

    @property
    def dispatcher_enabled(self) -> bool | None:
        """From the runtime-start note (None for timelines the runtime did not write)."""
        return self.start_note.get("dispatcher_enabled") if self.start_note else None

    @property
    def policy(self) -> str | None:
        """The policy the run executed: dispatcher | baseline (ignore the call) | pause_all. Runs logged
        before the policy field existed are inferred from dispatcher_enabled."""
        if not self.start_note:
            return None
        if self.start_note.get("policy"):
            return "dispatcher" if self.start_note["policy"] not in ("baseline", "pause_all") else self.start_note["policy"]
        return {True: "dispatcher", False: "baseline"}.get(self.start_note.get("dispatcher_enabled"))

    @property
    def cap(self) -> TimelineEvent | None:
        """The run's first cap event: the event window a report is about."""
        return self.caps[0] if self.caps else None

    @property
    def cap_w(self) -> float | None:
        return float(self.cap.data["target_w"]) if self.cap else None

    def cap_start(self) -> float | None:
        return _ts(self.cap.data["start"]) if self.cap else None

    def event_window(self) -> tuple[float, float] | None:
        """[cap start, cap end], cut at the last power sample or where the cap was withdrawn; None if no cap,
        or it starts after the data."""
        start = self.cap_start()
        if start is None or not self.power or start > self.power[-1][0]:
            return None
        end = start + float(self.cap.data["duration_s"])
        end = min([end] + [n.t for n in self.notes if n.data.get("cap_withdrawn") == self.cap.data.get("id")])
        return start, min(end, self.power[-1][0])

    def run_window(self) -> tuple[float, float]:
        if self.power:
            return self.power[0][0], self.power[-1][0]
        if self.first_t is None:
            raise ValueError(f"{self.path}: empty timeline, nothing to report")
        return self.first_t, self.last_t

    def default_window(self) -> tuple[float, float]:
        return self.event_window() or self.run_window()

    def watts(self, start: float, end: float) -> list[tuple[float, float]]:
        return [(t, w) for t, w in self.power if start <= t <= end]

    def grid_at(self, t: float) -> TimelineEvent | None:
        """The grid signal in effect at t: the newest one logged at or before t."""
        i = bisect.bisect_right(self._grid_t, t)
        return self.grid[i - 1] if i else None

    def sla_s(self) -> float | None:
        """The chat TTFT SLA in effect: the run's latest policy dump that carries one, else config."""
        for p in reversed(self.policies):
            v = (p.data.get("sla") or {}).get(SLA_KEY)
            if v is not None:
                return float(v)
        v = (config.policy.get("sla") or {}).get(SLA_KEY)
        return float(v) if v is not None else None


def _run_id(path: Path) -> str:
    return path.parent.name if path.name in ("timeline.jsonl", "timeline.jsonl.gz") else path.stem


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def time_to_compliance(run: Run, start: float, end: float, cap: float) -> float | None:
    """Seconds from `start` to the first sample in [start, end] whose trailing ROLLING_S mean (over
    every sample in that trailing span, including ones before the window) is at or under `cap`."""
    s = [(t, w) for t, w in run.power if start - ROLLING_S < t <= end]
    lo, total = 0, 0.0
    for i, (t, w) in enumerate(s):
        total += w
        while s[lo][0] <= t - ROLLING_S:
            total -= s[lo][1]
            lo += 1
        if t >= start and total / (i + 1 - lo) <= cap:
            return t - start
    return None


def integrate(run: Run, start: float, end: float) -> tuple[float, float, float, list[str]]:
    """Energy Wh, cost $ and gCO2 over [start, end] (trapezoids between consecutive samples).

    Each interval is priced at the grid signal in effect at its start. Gaps longer than MAX_GAP_S,
    and seconds with no price or carbon yet, are left out and reported, never filled."""
    s = run.watts(start, end)
    wh = usd = co2 = 0.0
    gaps = unpriced = uncarboned = 0.0
    for (t0, w0), (t1, w1) in zip(s, s[1:]):
        dt = t1 - t0
        if dt > MAX_GAP_S:
            gaps += dt
            continue
        e_wh = (w0 + w1) / 2 * dt / 3600
        wh += e_wh
        g = run.grid_at(t0)
        price = g.data.get("price_now") if g else None
        carbon = g.data.get("carbon_now") if g else None
        if price is None:
            unpriced += dt
        else:
            usd += e_wh / 1e6 * float(price)            # Wh/1e6 = MWh
        if carbon is None:
            uncarboned += dt
        else:
            co2 += e_wh / 1000 * float(carbon)          # Wh/1000 = kWh
    notes = []
    if not s:
        notes.append("no power samples in the window: energy, cost and carbon are not measured")
    if gaps:
        notes.append(f"meter gaps totalling {gaps:.0f} s were not integrated")
    if unpriced:
        notes.append(f"{unpriced:.0f} s had no live price logged yet and are not in the cost")
    if uncarboned:
        notes.append(f"{uncarboned:.0f} s had no live carbon intensity logged yet and are not in the gCO2")
    return wh, usd, co2, notes


def chat_p95(run: Run, start: float, end: float, key: str = "ttft_p95_60s") -> tuple[float | None, float | None]:
    """A chat trailing-60-s p95 as the proxy reports it (`key` of the chat job's state events):
    the last value logged before the window, and the worst value logged in it."""
    vals = [(e.t, float(e.data[key])) for e in run.chat if e.data.get(key) is not None]
    before = [v for t, v in vals if t < start]
    during = [v for t, v in vals if start <= t <= end]
    return (before[-1] if before else None), (max(during) if during else None)


def due_dates(run: Run, end: float) -> dict[str, float]:
    """Each job's deadline as of `end`: config/jobs.yaml, then the run's job-change events in order."""
    due = {j["id"]: _ts(j.get("deadline")) for j in config.jobs.get("jobs", [])}
    for p in run.policies:
        ch = p.data.get("changes") or {}
        if p.t <= end and p.data.get("reason") == "job change" and "deadline" in ch:
            due[p.data.get("job")] = _ts(ch["deadline"])
    return {j: d for j, d in due.items() if d is not None}


PROGRESS = {"train": "step", "batch": "items_done"}   # the field each workload counts its work in


def _progress_at(run: Run, job: str, t: float) -> tuple[float, float] | None:
    """(time, units done) from the job's newest state at or before t."""
    key = PROGRESS.get(job)
    st = [e for e in run.states if e.data.get("job") == job and e.t <= t and e.data.get(key) is not None]
    return (st[-1].t, float(st[-1].data[key])) if st else None


def work_done(run: Run, start: float, end: float) -> dict[str, float]:
    """Measured units of work each job completed inside [start, end] (train steps, batch items): its count
    at the end minus its count at the start (or at its first report inside the window)."""
    out = {}
    for job, key in PROGRESS.items():
        b = _progress_at(run, job, end)
        if b is None:
            continue
        a = _progress_at(run, job, start)
        if a is None:
            first = next((e for e in run.states if e.data.get("job") == job and start <= e.t <= end
                          and e.data.get(key) is not None), None)
            a = (first.t, float(first.data[key])) if first else b
        out[job] = b[1] - a[1]
    return out


def _projected(run: Run, job: str, due: float, end: float) -> tuple[bool, str] | None:
    """For a run that did not follow the dispatcher's plan: when would this job finish, at the GPU rate it
    measured, if the run's own policy carried on? pause_all keeps jobs paused until the cap ends."""
    now = _progress_at(run, job, end)
    if now is None:
        return None
    rates = [float(e.data["rate"]) for e in run.states if e.data.get("job") == job and e.data.get("state") == "running"
             and e.data.get("device") == "gpu" and e.data.get("rate")]
    total = next((float(e.data["total"]) for e in reversed(run.states)
                  if e.data.get("job") == job and e.data.get("total") is not None), None)
    if job == "train":
        total = next((float(j["target_steps"]) for j in config.jobs.get("jobs", [])
                      if j["id"] == "train" and j.get("target_steps")), total)
    if not rates or total is None:
        return None
    rate = sum(rates[-20:]) / len(rates[-20:])
    resume = end
    if run.policy == "pause_all" and run.cap is not None:
        cap_end = run.cap_start() + float(run.cap.data["duration_s"])
        if cap_end > end:
            resume = cap_end
    finish = resume + max(0.0, total - now[1]) / rate
    return finish <= due, (f"due {_fmt(due)}; projected {_fmt(finish)} from {total - now[1]:.0f} units left at the "
                           f"measured {rate:.1f}/s, resuming {_fmt(resume)} under this run's policy")


def deadlines(run: Run, end: float) -> dict[str, tuple[bool, str]]:
    """Per job with a deadline: (met, basis). Measured when the job finished or the deadline passed
    inside the run. Otherwise, for a dispatched run, whether its latest schedule (as of `end`) still
    meets it; for a run that did not follow that schedule (baseline, pause_all), a projection from its
    own measured progress and rate under its own policy."""
    latest = next((s for s in reversed(run.schedules) if s.t <= end), None)
    planned_miss = {m["job_id"] for m in (latest.data.get("deadline_misses", []) if latest else [])}
    out = {}
    for jid, d in due_dates(run, end).items():
        done = next((e.t for e in run.states if e.data.get("job") == jid and e.data.get("state") == "done"
                     and e.t <= end), None)
        if done is not None:
            out[jid] = (done <= d, f"finished {_fmt(done)}, due {_fmt(d)}")
        elif d <= end:
            out[jid] = (False, f"due {_fmt(d)}, passed unfinished")
        elif run.policy in ("baseline", "pause_all"):
            p = _projected(run, jid, d, end)
            if p is not None:
                out[jid] = p
        elif latest is not None:
            out[jid] = (jid not in planned_miss,
                        f"due {_fmt(d)}; not finished yet, judged on the latest schedule {latest.data.get('id', '')}")
    return out


def approvals(run: Run, end: float) -> list[dict]:
    """One entry per approval request asked by `end`, at its latest status: who was asked, what,
    when, the status, and who answered with what (the owner's reason in their words)."""
    out: dict[str, dict] = {}
    for e in run.approvals:
        if e.t > end:
            continue
        d = e.data
        if "request_id" in d:                       # an owner's reply, parsed by the negotiator
            a = out.get(d["request_id"])
            if a is not None:
                dec = d.get("decision") or {}
                a.update(who=d.get("who"), reply=dec.get("decision"), reason=dec.get("reason", ""),
                         new_deadline=dec.get("new_deadline"), replied_t=e.t)
        elif d.get("id"):                           # an ApprovalRequest, created or changing status
            a = out.setdefault(d["id"], {"id": d["id"], "when": d.get("t", e.t), "what": d.get("job_id"),
                                         "owner": d.get("owner"), "message": d.get("message", ""),
                                         "who": None, "reply": None, "reason": "", "new_deadline": None})
            a["decision"] = d.get("status")
            if d.get("decided_t") is not None:
                a["decided_t"] = d["decided_t"]
    return list(out.values())


def _dedupe(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def _worst_shortfalls(events: list[TimelineEvent]) -> list[str]:
    """One line per shortfall kind and job: the largest amount. A run re-solves often and logs the same shortfall
    with a slightly different amount each time (Krish 14:22: one report repeated it 12 times)."""
    worst: dict[tuple, TimelineEvent] = {}
    for e in events:
        key = (e.data.get("shortfall_kind"), e.data.get("job_id"))
        if key not in worst or float(e.data.get("amount") or 0) > float(worst[key].data.get("amount") or 0):
            worst[key] = e
    return _dedupe([e.data.get("message") or str(e.data) for e in sorted(worst.values(), key=lambda e: e.t)])


def build_report(timeline_path: str | Path, window: tuple[float, float] | None = None) -> Report:
    """The Report for one run over `window` (default: its first cap event, else the whole run)."""
    run = Run.load(timeline_path)
    start, end = window or run.default_window()
    t0, cap = run.cap_start(), run.cap_w
    # baseline, reduction and time to compliance describe the cap: only for a window inside it
    in_cap = run.event_window() is not None and t0 <= start
    baseline_w = _mean([w for t, w in run.power if t0 - BASELINE_S <= t < t0]) if in_cap else None
    event_w = _mean([w for _, w in run.watts(start, end)])
    reduction = (100 * (baseline_w - event_w) / baseline_w) if baseline_w and event_w is not None else None
    ttc = time_to_compliance(run, start, end, cap) if in_cap else None
    wh, usd, co2, notes = integrate(run, start, end)
    before, during = chat_p95(run, start, end)
    shortfalls = _worst_shortfalls([e for e in run.shortfalls if e.t <= end])
    if run.cap is None:
        shortfalls.append("no cap event in this run: the window is the whole run")
    elif window is None and run.event_window() is None:
        shortfalls.append(f"the cap starts {_fmt(t0)}, after the last power sample: the window is the whole run")
    elif in_cap and ttc is None and event_w is not None:
        shortfalls.append(f"the {ROLLING_S:.0f}-s mean never reached the {cap:.2f} W cap in the window")
    if in_cap and baseline_w is None:
        shortfalls.append(f"no power samples in the {BASELINE_S:.0f} s before the cap: no baseline")
    bg = [n for n in run.notes if n.data.get("trigger") == "background" and start <= n.t <= end]
    if bg:
        shortfalls.append(f"load outside the plan up to {max(float(n.data.get('background_w') or 0) for n in bg):.2f} W "
                          f"was measured and counted against the cap ({len(bg)} re-solve(s) for it): the window's "
                          f"watts include it")
    for n in run.notes:
        if n.data.get("trigger") == "fleet" and start <= n.t <= end:
            shortfalls.append(f"the fleet changed at {_fmt(n.t)} ({n.data.get('msg', '').replace('re-solve: ', '')}): "
                              f"the measured total before and after covers different machines")
    for job in PROGRESS:
        done = next((e for e in run.states if e.data.get("job") == job and e.data.get("state") == "done"
                     and e.t <= start), None)
        if done:
            shortfalls.append(f"{job} had already finished at {_fmt(done.t)}, before the window: "
                              f"its work in the window is 0 by construction")
    return Report(
        run_id=run.run_id, window_start=start, window_end=end, baseline_w=baseline_w, event_w=event_w,
        reduction_pct=reduction, time_to_compliance_s=ttc, energy_wh=wh, cost_usd=usd, co2_g=co2,
        deadlines={j: met for j, (met, _) in deadlines(run, end).items()},
        approvals=approvals(run, end), chat_p95_before_s=before, chat_p95_during_s=during,
        shortfalls=shortfalls + notes, work_done=work_done(run, start, end),
    )


# ---------------------------------------------------------------------------------------- runs on disk

def resolve(run: str, root: Path = RUNS) -> tuple[Path, str]:
    """A run id (or `latest`, the runtime's symlink) under root, or a path to a timeline file."""
    p = Path(run)
    if p.is_file():
        return p, _run_id(p)
    d = (Path(root) / run).resolve()
    return d / "timeline.jsonl", d.name


RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def run_path(run: str, root: Path = RUNS) -> Path:
    """The timeline of a run id under root (or `latest`). For the HTTP API: a run id only, never a path."""
    if not RUN_ID.fullmatch(run) or ".." in run:
        raise FileNotFoundError(f"not a run id: {run!r}")
    p = Path(root) / run / "timeline.jsonl"
    if not p.is_file():
        raise FileNotFoundError(f"no timeline for run {run!r}")
    return p


def run_series(path: str | Path) -> dict:
    """One run's measured record for drawing, as its timeline logged it: 1-Hz combined watts, cap windows
    (start and end as epoch seconds), control actions and shortfall messages."""
    r = Run.load(path)
    caps = []
    for c in r.caps:
        start = _ts(c.data["start"])
        caps.append({"id": c.data.get("id"), "start": start, "end": start + float(c.data["duration_s"]),
                     "target_w": float(c.data["target_w"]), "target_pct": c.data.get("target_pct"),
                     "source": c.data.get("source"), "reason": c.data.get("reason")})
    return {"run_id": r.run_id, "policy": r.policy, "dispatcher_enabled": r.dispatcher_enabled,
            "machine": (r.start_note or {}).get("machine"), "started": r.first_t, "ended": r.last_t,
            "power": [[t, w] for t, w in r.power], "caps": caps,
            "actions": [{"t": a.t, **a.data} for a in r.actions],
            "shortfalls": [{"t": f.t, "shortfall_kind": f.data.get("shortfall_kind"), "job_id": f.data.get("job_id"),
                            "message": f.data.get("message")} for f in r.shortfalls]}


def runtime_runs(root: Path = RUNS) -> list[dict]:
    """Runs the runtime wrote (`make demo` / `make baseline`), oldest first, from each timeline's
    first event: the "runtime start" note with dispatcher_enabled."""
    out = []
    for tl in sorted(Path(root).glob("*/timeline.jsonl")):
        if tl.parent.is_symlink():
            continue
        try:
            with open(tl, encoding="utf-8") as fh:
                first = json.loads(fh.readline())
        except (OSError, json.JSONDecodeError):
            continue
        d = first.get("data", {})
        if first.get("kind") == "note" and d.get("msg") == "runtime start":
            pol = d.get("policy") or {True: "dispatcher", False: "baseline"}.get(d.get("dispatcher_enabled"))
            out.append({"run_id": tl.parent.name, "path": tl, "started": first["t"],
                        "dispatcher_enabled": d.get("dispatcher_enabled"), "machine": d.get("machine"),
                        "policy": "dispatcher" if pol not in ("baseline", "pause_all") else pol})
    return sorted(out, key=lambda r: r["started"])


def newest(dispatcher_enabled: bool, root: Path = RUNS, policy: str | None = None) -> Path:
    """Newest dispatched run, or newest run of a dispatcher-off `policy` (default `baseline`)."""
    want = "dispatcher" if dispatcher_enabled else (policy or "baseline")
    runs = [r for r in runtime_runs(root) if r["policy"] == want]
    if not runs:
        raise FileNotFoundError(f"no {want} run under {root}/")
    return runs[-1]["path"]


# ---------------------------------------------------------------------------------------- comparison

def share_under(run: Run, start: float, end: float, cap: float | None) -> float | None:
    """Fraction of measured samples in [start, end] at or under the cap."""
    s = run.watts(start, end)
    if cap is None or not s:
        return None
    return sum(w <= cap for _, w in s) / len(s)


def compare_runs(dispatched: str | Path, baseline: str | Path) -> Comparison:
    """Dispatched vs dispatcher-off, both measured over the same length of window: each from its own
    cap start (or its first power sample when it logged no cap), cut to the shorter of the two.
    Each run is priced at its own live price and mix. `delta` is dispatched minus baseline."""
    runs = {"dispatched": Run.load(dispatched), "baseline": Run.load(baseline)}
    wins = {k: r.default_window() for k, r in runs.items()}
    span = max(0.0, min(e - s for s, e in wins.values()))
    reps = {k: build_report(r.path, window=(wins[k][0], wins[k][0] + span)) for k, r in runs.items()}
    d, b = reps["dispatched"], reps["baseline"]
    notes = []
    for k, r in runs.items():
        how = f"from its cap start {_fmt(wins[k][0])}" if r.event_window() else f"from its first sample {_fmt(wins[k][0])}"
        notes.append(f"{k} run {r.run_id}: {span:.0f} s {how}")
        if r.dispatcher_enabled is None:
            notes.append(f"{k} run {r.run_id} has no runtime-start note: its mode is not on the timeline")
        elif r.dispatcher_enabled != (k == "dispatched"):
            notes.append(f"{k} run {r.run_id} started with the dispatcher {'on' if r.dispatcher_enabled else 'off'}")
        if any(p.data.get("reason") == "dispatcher toggle" for p in r.policies):
            notes.append(f"{k} run {r.run_id} toggled the dispatcher during the run")
    cap = runs["dispatched"].cap_w if runs["dispatched"].cap_w is not None else runs["baseline"].cap_w
    under = {k: share_under(runs[k], reps[k].window_start, reps[k].window_end, cap) for k in runs}
    if cap is not None:
        notes.append(f"cap {cap:.2f} W (the dispatched run's, else the baseline's) applied to both runs")
        notes.append("measured seconds at or under the cap: " + ", ".join(
            f"{k} {'n/a' if u is None else f'{100 * u:.0f} %'}" for k, u in under.items()))
    pairs = {"cost_usd": (d.cost_usd, b.cost_usd), "co2_g": (d.co2_g, b.co2_g),
             "energy_wh": (d.energy_wh, b.energy_wh), "event_w": (d.event_w, b.event_w),
             "chat_p95_s": (d.chat_p95_during_s, b.chat_p95_during_s),
             "time_to_compliance_s": (d.time_to_compliance_s, b.time_to_compliance_s),
             "deadlines_met": (float(sum(d.deadlines.values())) if d.deadlines else None,
                               float(sum(b.deadlines.values())) if b.deadlines else None),
             "under_cap_pct": tuple(None if under[k] is None else 100 * under[k] for k in ("dispatched", "baseline"))}
    for job in PROGRESS:
        pairs[f"work_{job}"] = (d.work_done.get(job), b.work_done.get(job))
    delta = {k: x - y for k, (x, y) in pairs.items() if x is not None and y is not None}
    return Comparison(dispatched=d, baseline=b, window_s=span, delta=delta, notes=notes,
                      under_cap_pct={k: None if under[k] is None else 100 * under[k] for k in ("dispatched", "baseline")})


# ---------------------------------------------------------------------------------------- rendering

def _fmt(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone().strftime("%a %H:%M:%S %Z")


def _num(v, spec: str, unit: str = "") -> str:
    return "n/a" if v is None else f"{v:{spec}}{unit}"


def chart(run: Run, rep: Report, out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pad = BASELINE_S if rep.baseline_w is not None else 0.0
    s = run.watts(rep.window_start - pad, rep.window_end)
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot([t - rep.window_start for t, _ in s], [w for _, w in s], lw=1.2, color="#1f6feb",
            label="measured W (powermetrics)")
    if rep.baseline_w is not None:
        ax.axhline(rep.baseline_w, ls=":", color="#6e7781", label=f"pre-cap baseline {rep.baseline_w:.2f} W")
    if run.event_window() is not None:
        ax.axhline(run.cap_w, ls="--", color="#cf222e", label=f"cap {run.cap_w:.2f} W")
        ax.axvspan(0, rep.window_end - rep.window_start, color="#cf222e", alpha=0.06)
    if rep.time_to_compliance_s is not None:
        ax.axvline(rep.time_to_compliance_s, color="#1a7f37", lw=1,
                   label=f"compliant at +{rep.time_to_compliance_s:.0f} s")
    ax.set_xlabel("seconds from window start")
    ax.set_ylabel("W")
    ax.set_title(f"Run {rep.run_id}: measured SoC power")
    if s:
        ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def shown(path: Path) -> str:
    """A timeline's path as a reader of the repo would open it: relative to here when it is inside."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_markdown(run: Run, rep: Report, chart_name: str | None) -> str:
    ev = run.cap if run.event_window() is not None else None
    sla = run.sla_s()
    tot_before, tot_during = chat_p95(run, rep.window_start, rep.window_end, key="p95_60s")
    lines = [f"# Griddy report: run {rep.run_id}", "",
             f"Window {_fmt(rep.window_start)} to {_fmt(rep.window_end)} "
             f"({rep.window_end - rep.window_start:.0f} s). Computed from `{shown(run.path)}` only: "
             "watts are powermetrics samples (SoC: CPU + GPU + ANE), $ and gCO2 use the live price and fuel "
             "mix in effect at each second.", ""]
    if ev is not None:
        lines += [f"Cap event: {ev.data.get('reason') or 'cap'} (source {ev.data.get('source', '?')}), "
                  f"{run.cap_w:.2f} W for {ev.data['duration_s']} s from {_fmt(run.cap_start())}"
                  + (f" ({ev.data['target_pct']:g} % below the measured baseline)" if ev.data.get("target_pct") else "")
                  + ".", ""]
    lines += ["| Measure | Value |", "|---|---|",
              f"| Pre-cap baseline ({BASELINE_S:.0f} s mean) | {_num(rep.baseline_w, '.2f', ' W')} |",
              f"| {'Cap window' if ev is not None else 'Window'} mean | {_num(rep.event_w, '.2f', ' W')} |",
              f"| Reduction | {_num(rep.reduction_pct, '.1f', ' %')} |",
              f"| Time to compliance ({ROLLING_S:.0f}-s mean at or under cap) | "
              f"{_num(rep.time_to_compliance_s, '.0f', ' s')} |",
              f"| Energy | {rep.energy_wh:.3f} Wh |",
              f"| Cost at live price | ${rep.cost_usd:.6f} |",
              f"| Carbon at live mix | {rep.co2_g:.3f} gCO2 |",
              f"| Chat time-to-first-token p95, trailing 60 s (SLA {_num(sla, 'g', ' s')}): last before / "
              f"worst during | {_num(rep.chat_p95_before_s, '.2f', ' s')} / {_num(rep.chat_p95_during_s, '.2f', ' s')} |",
              f"| Chat total-latency p95, trailing 60 s (reported, not an SLA): last before / worst during | "
              f"{_num(tot_before, '.2f', ' s')} / {_num(tot_during, '.2f', ' s')} |", ""]
    dl = deadlines(run, rep.window_end)
    if dl:
        lines += ["## Deadlines", ""] + [f"- {j}: {'met' if m else 'MISSED'} ({basis})" for j, (m, basis) in dl.items()]
        lines.append("")
    if rep.approvals:
        lines += ["## Approvals", ""]
        for a in rep.approvals:
            line = f"- {_fmt(a['when'])}: asked {a['owner']} about {a['what']}: {a['decision']}"
            if a["who"]:
                line += f"; {a['who']} replied {a['reply']}" + (f" (\"{a['reason']}\")" if a["reason"] else "")
            lines.append(line)
        lines.append("")
    if rep.shortfalls:
        lines += ["## Shortfalls and caveats", ""] + [f"- {s}" for s in rep.shortfalls] + [""]
    if chart_name:
        lines += [f"![measured power]({chart_name})", ""]
    return "\n".join(lines)


def write(timeline_path: Path, out_dir: Path, run_id: str | None = None) -> Path:
    run = Run.load(timeline_path, run_id)
    rep = build_report(timeline_path).model_copy(update={"run_id": run.run_id})
    out_dir.mkdir(parents=True, exist_ok=True)
    png = chart(run, rep, out_dir / f"{run.run_id}-power.png")
    md = out_dir / f"{run.run_id}.md"
    md.write_text(render_markdown(run, rep, png.name), encoding="utf-8")
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="latest", help="run id under runs/, 'latest', or a timeline path")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    path, run_id = resolve(a.run)
    if not path.is_file():
        ap.error(f"no timeline at {path}")
    md = write(path, Path(a.out), run_id)
    print(md.read_text(encoding="utf-8"))
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
