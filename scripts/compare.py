"""Dispatched vs dispatcher-off, from two logged runs (`make compare`).

    python scripts/compare.py                                   # newest dispatched run vs newest baseline run
    python scripts/compare.py --dispatched <id> --baseline <id>  # (make compare DISPATCHED=<id> BASELINE=<id>)

A run's mode is the `dispatcher_enabled` of its "runtime start" note. The numbers are
agent.reporter.compare_runs (the Comparison served at /api/compare); this script renders them as a
markdown table and a power chart in reports/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from agent.reporter import RUNS, Run, chat_p95, compare_runs, newest, resolve, share_under
from core.types import Comparison, Report


def _f(v, spec, unit=""):
    return "n/a" if v is None else f"{v:{spec}}{unit}"


def _d(c: Comparison, key: str, spec: str, unit: str = "") -> str:
    v = c.delta.get(key)
    return "" if v is None else f"{v:+{spec}}{unit}"


def _pct(x: float | None) -> float | None:
    return None if x is None else 100 * x


def _met(r: Report) -> str:
    return f"{sum(r.deadlines.values())}/{len(r.deadlines)}" if r.deadlines else "n/a"


def table(c: Comparison, runs: dict[str, Run]) -> str:
    d, b = c.dispatched, c.baseline
    tot = {k: chat_p95(runs[k], r.window_start, r.window_end, key="p95_60s")[1]
           for k, r in (("dispatched", d), ("baseline", b))}
    sla = runs["dispatched"].sla_s()
    cap = runs["dispatched"].cap_w if runs["dispatched"].cap_w is not None else runs["baseline"].cap_w
    under = {k: share_under(runs[k], r.window_start, r.window_end, cap) for k, r in (("dispatched", d), ("baseline", b))}
    lines = [
        f"# Dispatched vs baseline over {c.window_s:.0f} s", "",
        f"Dispatched run `{d.run_id}` vs `{runs['baseline'].policy or 'dispatcher-off'}` run `{b.run_id}`. "
        "Computed from their timelines only "
        "(powermetrics watts; each run priced at the live price and fuel mix it had).", "",
        "| Measure | Dispatched | Baseline | Dispatched minus baseline |", "|---|---|---|---|",
        f"| Cost at live price | ${d.cost_usd:.6f} | ${b.cost_usd:.6f} | {_d(c, 'cost_usd', '.6f')} |",
        f"| Carbon at live mix | {d.co2_g:.3f} g | {b.co2_g:.3f} g | {_d(c, 'co2_g', '.3f', ' g')} |",
        f"| Energy (measured) | {d.energy_wh:.3f} Wh | {b.energy_wh:.3f} Wh | {_d(c, 'energy_wh', '.3f', ' Wh')} |",
        f"| Mean power | {_f(d.event_w, '.2f', ' W')} | {_f(b.event_w, '.2f', ' W')} | {_d(c, 'event_w', '.2f', ' W')} |",
        f"| Time to compliance | {_f(d.time_to_compliance_s, '.0f', ' s')} | {_f(b.time_to_compliance_s, '.0f', ' s')} | "
        f"{_d(c, 'time_to_compliance_s', '.0f', ' s')} |",
        f"| Deadlines met | {_met(d)} | {_met(b)} | {_d(c, 'deadlines_met', '.0f')} |",
        f"| Chat time-to-first-token p95, worst trailing 60 s (SLA {_f(sla, 'g', ' s')}) | "
        f"{_f(d.chat_p95_during_s, '.2f', ' s')} | {_f(b.chat_p95_during_s, '.2f', ' s')} | {_d(c, 'chat_p95_s', '.2f', ' s')} |",
        f"| Chat total-latency p95, worst trailing 60 s (reported, not an SLA) | "
        f"{_f(tot['dispatched'], '.2f', ' s')} | {_f(tot['baseline'], '.2f', ' s')} | |",
        f"| Measured seconds at or under the cap | {_f(_pct(under['dispatched']), '.0f', ' %')} | "
        f"{_f(_pct(under['baseline']), '.0f', ' %')} | {_d(c, 'under_cap_pct', '.0f', ' points')} |",
        f"| Training done in the window (steps, measured) | {_f(d.work_done.get('train'), '.0f')} | "
        f"{_f(b.work_done.get('train'), '.0f')} | {_d(c, 'work_train', '.0f')} |",
        f"| Batch done in the window (items, measured) | {_f(d.work_done.get('batch'), '.0f')} | "
        f"{_f(b.work_done.get('batch'), '.0f')} | {_d(c, 'work_batch', '.0f')} |", ""]
    lines += ["## Notes", ""] + [f"- {n}" for n in c.notes] + [""]
    caveats = [f"- {label}: {s}" for label, r in (("dispatched", d), ("baseline", b)) for s in r.shortfalls]
    if caveats:
        lines += ["## Shortfalls and caveats", ""] + caveats + [""]
    return "\n".join(lines)


def chart(c: Comparison, runs: dict[str, Run], out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 3.6))
    for (label, rep), color in zip((("dispatched", c.dispatched), ("baseline", c.baseline)), ("#1f6feb", "#bc4c00")):
        s = runs[label].watts(rep.window_start, rep.window_end)
        ax.plot([t - rep.window_start for t, _ in s], [w for _, w in s], lw=1.2, color=color,
                label=f"{label} ({rep.run_id})")
    cap = runs["dispatched"].cap_w if runs["dispatched"].cap_w is not None else runs["baseline"].cap_w
    if cap is not None:
        ax.axhline(cap, ls="--", color="#cf222e", label=f"cap {cap:.2f} W")
    ax.set_xlabel("seconds from window start")
    ax.set_ylabel("measured W (powermetrics)")
    ax.set_title("Dispatched vs baseline: measured SoC power")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def write(dispatched: Path, baseline: Path, out: Path) -> Path:
    """Compare two timelines and write compare-<d>-vs-<b>.md and its chart into `out`."""
    c = compare_runs(dispatched, baseline)
    runs = {k: Run.load(p, run_id=r.run_id) for (k, p), r in zip({"dispatched": dispatched, "baseline": baseline}.items(),
                                                                  (c.dispatched, c.baseline))}
    out.mkdir(parents=True, exist_ok=True)
    name = f"compare-{c.dispatched.run_id}-vs-{c.baseline.run_id}"
    png = chart(c, runs, out / f"{name}.png")
    md = out / f"{name}.md"
    md.write_text(table(c, runs) + f"\n![measured power]({png.name})\n", encoding="utf-8")
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dispatched", help="run id or timeline path (default: newest dispatched run)")
    ap.add_argument("--baseline", help="run id or timeline path (default: newest run of --baseline-policy)")
    ap.add_argument("--baseline-policy", default="baseline", choices=["baseline", "pause_all"],
                    help="which dispatcher-off policy to compare against when --baseline is not given")
    ap.add_argument("--runs", default=str(RUNS), help="where runs live (default: runs/)")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    root = Path(a.runs)
    try:
        paths = {"dispatched": resolve(a.dispatched, root)[0] if a.dispatched else newest(True, root),
                 "baseline": resolve(a.baseline, root)[0] if a.baseline else newest(False, root, a.baseline_policy)}
    except FileNotFoundError as e:
        ap.error(f"{e}; or pass --dispatched/--baseline")
    for k, p in paths.items():
        if not p.is_file():
            ap.error(f"{k}: no timeline at {p}")
    md = write(paths["dispatched"], paths["baseline"], Path(a.out))
    print(md.read_text(encoding="utf-8"))
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
