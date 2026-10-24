"""Event-window report from a timeline, and nothing else (SPEC §9, CLAUDE.md rule 4).

Every number is computed from the `power`, `grid`, `event`, `latency`, `state`, `approval`,
`schedule` and `shortfall` events one run logged. Watts are powermetrics samples; prices and carbon
are the live values the run had in effect at each second. Nothing is estimated or typed in.

    python -m agent.reporter --run <id>      # writes reports/<id>.md and reports/<id>-power.png
"""
from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import jobs as JOBS_CFG
from core.timeline import Timeline
from core.types import Report, TimelineEvent

BASELINE_S = 60.0      # pre-event baseline: mean measured W over this many seconds before the event
ROLLING_S = 10.0       # compliance: the trailing mean over this many seconds must be at or under the cap
MAX_GAP_S = 5.0        # meter gaps longer than this are not integrated (no energy is invented for them)


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v)).timestamp()


@dataclass
class Run:
    """A timeline split by kind, in time order."""

    run_id: str
    path: Path
    power: list[tuple[float, float]] = field(default_factory=list)      # (t, combined W)
    grid: list[TimelineEvent] = field(default_factory=list)
    events: list[TimelineEvent] = field(default_factory=list)
    latency: list[TimelineEvent] = field(default_factory=list)
    states: list[TimelineEvent] = field(default_factory=list)
    approvals: list[TimelineEvent] = field(default_factory=list)
    schedules: list[TimelineEvent] = field(default_factory=list)
    shortfalls: list[TimelineEvent] = field(default_factory=list)
    plans: list[TimelineEvent] = field(default_factory=list)
    policies: list[TimelineEvent] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path, run_id: str | None = None) -> Run:
        path = Path(path)
        r = cls(run_id=run_id or path.parent.name, path=path)
        buckets = {"grid": r.grid, "event": r.events, "latency": r.latency, "state": r.states,
                   "approval": r.approvals, "schedule": r.schedules, "shortfall": r.shortfalls,
                   "plan": r.plans, "policy": r.policies}
        for ev in sorted(Timeline.read(path), key=lambda e: e.t):
            if ev.kind == "power" and ev.data.get("combined_w") is not None:
                r.power.append((float(ev.data.get("t", ev.t)), float(ev.data["combined_w"])))
            elif ev.kind in buckets:
                buckets[ev.kind].append(ev)
        r.power.sort()
        return r

    @property
    def mode(self) -> str | None:
        """'dispatcher' or 'baseline', from the slot plans the run executed (majority)."""
        modes = [p.data.get("mode") for p in self.plans if p.data.get("mode")]
        return max(set(modes), key=modes.count) if modes else None

    @property
    def first_event(self) -> TimelineEvent | None:
        return self.events[0] if self.events else None

    def event_window(self) -> tuple[float, float] | None:
        ev = self.first_event
        if ev is None:
            return None
        start = _ts(ev.data.get("start")) or ev.t
        end = start + float(ev.data["duration_s"]) if ev.data.get("duration_s") else None
        last = self.power[-1][0] if self.power else start
        return start, min(end, last) if end is not None else last

    def default_window(self) -> tuple[float, float]:
        w = self.event_window()
        if w is not None:
            return w
        if not self.power:
            raise ValueError(f"{self.path}: no power samples, nothing to report")
        return self.power[0][0], self.power[-1][0]

    def watts(self, start: float, end: float) -> list[tuple[float, float]]:
        return [(t, w) for t, w in self.power if start <= t <= end]

    def cap_w(self, baseline_w: float | None) -> float | None:
        ev = self.first_event
        if ev is None:
            return None
        if ev.data.get("target_w") is not None:
            return float(ev.data["target_w"])
        if ev.data.get("target_pct") is not None and baseline_w is not None:
            return baseline_w * (1 - float(ev.data["target_pct"]) / 100)
        return None

    def grid_at(self, t: float) -> TimelineEvent | None:
        """The grid signal in effect at t: the newest one logged at or before t."""
        cur = None
        for g in self.grid:
            if g.t > t:
                break
            cur = g
        return cur


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def time_to_compliance(samples: list[tuple[float, float]], start: float, cap: float) -> float | None:
    """Seconds from `start` to the first sample whose trailing ROLLING_S mean is at or under `cap`."""
    lo, total = 0, 0.0
    for i, (t, w) in enumerate(samples):
        total += w
        while samples[lo][0] <= t - ROLLING_S:
            total -= samples[lo][1]
            lo += 1
        if total / (i + 1 - lo) <= cap:
            return t - start
    return None


def integrate(run: Run, start: float, end: float) -> tuple[float, float, float, list[str]]:
    """Energy Wh, cost $ and gCO2 over [start, end] (trapezoids between consecutive samples).

    Each interval is priced at the grid signal in effect at its start. Gaps longer than MAX_GAP_S,
    and seconds with no price or carbon yet, are left out and reported, never filled."""
    s = run.watts(start, end)
    wh = usd = co2 = 0.0
    gaps, unpriced, uncarboned = 0.0, 0.0, 0.0
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
    if gaps:
        notes.append(f"meter gaps totalling {gaps:.0f} s were not integrated")
    if unpriced:
        notes.append(f"{unpriced:.0f} s had no live price logged yet and are not in the cost")
    if uncarboned:
        notes.append(f"{uncarboned:.0f} s had no live carbon intensity logged yet and are not in the gCO2")
    return wh, usd, co2, notes


def p95_before_during(run: Run, start: float, end: float) -> tuple[float | None, float | None]:
    """Chat p95 (trailing 60 s, as the proxy logs it): last value before the window, worst value in it."""
    before = [e.data["p95_60s"] for e in run.latency if e.t < start and e.data.get("p95_60s") is not None]
    during = [e.data["p95_60s"] for e in run.latency if start <= e.t <= end and e.data.get("p95_60s") is not None]
    return (before[-1] if before else None), (max(during) if during else None)


def deadlines(run: Run, end: float) -> dict[str, tuple[bool, str]]:
    """Per job with a deadline: (met, basis). Measured when the job finished or the deadline passed
    inside the run; otherwise whether the run's latest solved schedule still meets it."""
    due = {j["id"]: _ts(j["deadline"]) for j in JOBS_CFG.get("jobs", []) if j.get("deadline")}
    latest = next((s for s in reversed(run.schedules) if s.t <= end), None)
    planned_miss = {m["job_id"]: m for m in (latest.data.get("deadline_misses", []) if latest else [])}
    for jid, m in planned_miss.items():
        due[jid] = _ts(m["deadline"])
    out = {}
    for jid, d in due.items():
        done = next((e.t for e in run.states if e.data.get("job") == jid and e.data.get("state") == "done"
                     and e.t <= end), None)
        if done is not None:
            out[jid] = (done <= d, "finished " + _fmt(done))
        elif d <= end:
            out[jid] = (False, "deadline passed unfinished")
        elif latest is not None:
            out[jid] = (jid not in planned_miss, f"on the latest schedule {latest.data.get('id', '')}")
    return out


def approvals(run: Run, end: float) -> list[dict]:
    out = []
    for e in run.approvals:
        if e.t > end:
            continue
        d = e.data
        out.append({"t": e.t, "who": d.get("approver") or d.get("owner"),
                    "what": d.get("job_id") or d.get("plan_id") or d.get("what"),
                    "decision": d.get("decision") or d.get("status"), "reason": d.get("reason", "")})
    return out


def build_report(timeline_path: str | Path, window: tuple[float, float] | None = None) -> Report:
    run = Run.load(timeline_path)
    start, end = window or run.default_window()
    ev = run.first_event
    baseline_w = None
    if ev is not None:
        t0 = _ts(ev.data.get("start")) or ev.t
        baseline_w = _mean([w for _, w in run.watts(t0 - BASELINE_S, t0 - 1e-9)])
    in_window = run.watts(start, end)
    event_w = _mean([w for _, w in in_window])
    cap = run.cap_w(baseline_w)
    reduction = (100 * (baseline_w - event_w) / baseline_w) if baseline_w and event_w is not None else None
    ttc = time_to_compliance(in_window, start, cap) if cap is not None else None
    wh, usd, co2, notes = integrate(run, start, end)
    before, during = p95_before_during(run, start, end)
    shortfalls = [e.data.get("message") or str(e.data) for e in run.shortfalls if e.t <= end]
    if cap is not None and ttc is None:
        shortfalls.append(f"the {ROLLING_S:.0f}-s mean never reached the {cap:.1f} W cap in the window")
    if ev is not None and baseline_w is None:
        shortfalls.append(f"no power samples in the {BASELINE_S:.0f} s before the event: no baseline")
    return Report(
        run_id=run.run_id, window_start=start, window_end=end, baseline_w=baseline_w, event_w=event_w,
        reduction_pct=reduction, time_to_compliance_s=ttc, energy_wh=wh, cost_usd=usd, co2_g=co2,
        deadlines={j: met for j, (met, _) in deadlines(run, end).items()},
        approvals=approvals(run, end), chat_p95_before_s=before, chat_p95_during_s=during,
        shortfalls=shortfalls + notes,
    )


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
        ax.axhline(rep.baseline_w, ls=":", color="#6e7781", label=f"pre-event baseline {rep.baseline_w:.1f} W")
    cap = run.cap_w(rep.baseline_w)
    if cap is not None:
        ax.axhline(cap, ls="--", color="#cf222e", label=f"cap {cap:.1f} W")
        ax.axvspan(0, rep.window_end - rep.window_start, color="#cf222e", alpha=0.06)
    if rep.time_to_compliance_s is not None:
        ax.axvline(rep.time_to_compliance_s, color="#1a7f37", lw=1,
                   label=f"compliant at +{rep.time_to_compliance_s:.0f} s")
    ax.set_xlabel("seconds from window start")
    ax.set_ylabel("W")
    ax.set_title(f"Run {rep.run_id}: measured SoC power")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def render_markdown(run: Run, rep: Report, chart_name: str | None) -> str:
    cap = run.cap_w(rep.baseline_w)
    ev = run.first_event
    lines = [f"# Brownout report: run {rep.run_id}", "",
             f"Window {_fmt(rep.window_start)} to {_fmt(rep.window_end)} "
             f"({rep.window_end - rep.window_start:.0f} s). Computed from `{run.path.as_posix()}` only: "
             f"watts are powermetrics samples, $ and gCO2 use the live price and fuel mix in effect each second.", ""]
    if ev is not None:
        lines += [f"Event: {ev.data.get('reason') or 'cap event'} (source {ev.data.get('source', 'ui')}), "
                  f"cap {_num(cap, '.1f', ' W')}.", ""]
    lines += ["| Measure | Value |", "|---|---|",
              f"| Pre-event baseline ({BASELINE_S:.0f} s mean) | {_num(rep.baseline_w, '.2f', ' W')} |",
              f"| {'Event' if ev is not None else 'Window'} mean | {_num(rep.event_w, '.2f', ' W')} |",
              f"| Reduction | {_num(rep.reduction_pct, '.1f', ' %')} |",
              f"| Time to compliance ({ROLLING_S:.0f}-s mean at or under cap) | "
              f"{_num(rep.time_to_compliance_s, '.0f', ' s')} |",
              f"| Energy | {rep.energy_wh:.3f} Wh |",
              f"| Cost at live price | ${rep.cost_usd:.6f} |",
              f"| Carbon at live mix | {rep.co2_g:.3f} gCO2 |",
              f"| Chat p95 before / during | {_num(rep.chat_p95_before_s, '.2f', ' s')} / "
              f"{_num(rep.chat_p95_during_s, '.2f', ' s')} |", ""]
    dl = deadlines(run, rep.window_end)
    if dl:
        lines += ["## Deadlines", ""] + [f"- {j}: {'met' if m else 'MISSED'} ({basis})" for j, (m, basis) in dl.items()]
        lines.append("")
    if rep.approvals:
        lines += ["## Approvals", ""] + [
            f"- {_fmt(a['t'])}: {a['who']} {a['decision']} {a['what']}" + (f" — \"{a['reason']}\"" if a["reason"] else "")
            for a in rep.approvals]
        lines.append("")
    if rep.shortfalls:
        lines += ["## Shortfalls and caveats", ""] + [f"- {s}" for s in rep.shortfalls] + [""]
    if chart_name:
        lines += [f"![measured power]({chart_name})", ""]
    return "\n".join(lines)


def write(timeline_path: Path, out_dir: Path, run_id: str | None = None) -> Path:
    run = Run.load(timeline_path, run_id)
    rep = build_report(timeline_path)
    rep.run_id = run.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    png = chart(run, rep, out_dir / f"{run.run_id}-power.png")
    md = out_dir / f"{run.run_id}.md"
    md.write_text(render_markdown(run, rep, png.name), encoding="utf-8")
    return md


def resolve(run: str, root: Path = Path("runs")) -> tuple[Path, str]:
    """A run id (or `latest`) under runs/, or a path to a timeline.jsonl."""
    p = Path(run)
    if p.is_file():
        return p, p.parent.name if p.name == "timeline.jsonl" else p.stem
    d = (root / run).resolve()
    return d / "timeline.jsonl", d.name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="latest", help="run id under runs/, 'latest', or a timeline path")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    path, run_id = resolve(a.run)
    md = write(path, Path(a.out), run_id)
    print(md.read_text(encoding="utf-8"))
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
