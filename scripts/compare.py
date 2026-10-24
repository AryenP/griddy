"""Dispatched vs dispatcher-off, from two logged runs (`make compare`).

    python scripts/compare.py                                   # newest dispatcher run vs newest baseline run
    python scripts/compare.py --dispatched <id> --baseline <id>

A run's mode comes from the slot plans it executed (`plan.mode`). Both runs are compared over the
same length of window: each from its own event start (or run start), cut to the shorter of the two.
Every number comes from agent/reporter.py over that window; each run is priced at its own live price.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from agent.reporter import Run, build_report, resolve
from core.types import Report

RUNS = Path("runs")


def newest(mode: str, root: Path = RUNS) -> Path:
    for p in sorted(root.glob("*/timeline.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.parent.is_symlink():
            continue
        if Run.load(p).mode == mode:
            return p
    raise SystemExit(f"no {mode} run under {root}/ (run `make demo` and `make baseline` first)")


def share_under(run: Run, start: float, end: float, cap: float | None) -> float | None:
    """Fraction of measured seconds in the window at or under the cap."""
    s = run.watts(start, end)
    if cap is None or not s:
        return None
    return sum(w <= cap for _, w in s) / len(s)


def compare(dispatched: Path, baseline: Path) -> tuple[list[tuple[str, Run, Report, float | None]], float | None]:
    runs = [("dispatched", Run.load(dispatched)), ("baseline", Run.load(baseline))]
    windows = [r.default_window() for _, r in runs]
    span = min(e - s for s, e in windows)
    out, ref_cap = [], None
    for (label, run), (s, _) in zip(runs, windows):
        rep = build_report(run.path, window=(s, s + span))
        rep.run_id = run.run_id
        cap = run.cap_w(rep.baseline_w)
        ref_cap = ref_cap if ref_cap is not None else cap
        out.append((label, run, rep, cap if cap is not None else ref_cap))
    return out, span


def _f(v, spec, unit=""):
    return "n/a" if v is None else f"{v:{spec}}{unit}"


def _delta(a, b, spec, unit=""):
    return "" if a is None or b is None else f"{b - a:+{spec}}{unit}"


def _met(r: Report) -> str:
    return f"{sum(r.deadlines.values())}/{len(r.deadlines)}" if r.deadlines else "n/a"


def table(rows, span: float) -> str:
    (_, _, d, cap_d), (_, _, b, cap_b) = rows
    ud = share_under(rows[0][1], d.window_start, d.window_end, cap_d)
    ub = share_under(rows[1][1], b.window_start, b.window_end, cap_b)
    lines = [
        f"# Dispatched vs baseline over {span:.0f} s", "",
        f"Dispatched run `{d.run_id}` vs dispatcher-off run `{b.run_id}`. Computed from their timelines only; "
        "each run is priced at the live price and fuel mix it had.", "",
        "| Measure | Dispatched | Baseline | Baseline minus dispatched |", "|---|---|---|---|",
        f"| Cost at live price | ${d.cost_usd:.6f} | ${b.cost_usd:.6f} | {_delta(d.cost_usd, b.cost_usd, '.6f')} |",
        f"| Carbon at live mix | {d.co2_g:.3f} g | {b.co2_g:.3f} g | {_delta(d.co2_g, b.co2_g, '.3f', ' g')} |",
        f"| Energy (measured) | {d.energy_wh:.3f} Wh | {b.energy_wh:.3f} Wh | "
        f"{_delta(d.energy_wh, b.energy_wh, '.3f', ' Wh')} |",
        f"| Mean power | {_f(d.event_w, '.2f', ' W')} | {_f(b.event_w, '.2f', ' W')} | "
        f"{_delta(d.event_w, b.event_w, '.2f', ' W')} |",
        f"| Seconds at or under cap | {_f(ud and 100 * ud, '.0f', ' %')} | {_f(ub and 100 * ub, '.0f', ' %')} | |",
        f"| Time to compliance | {_f(d.time_to_compliance_s, '.0f', ' s')} | "
        f"{_f(b.time_to_compliance_s, '.0f', ' s')} | |",
        f"| Deadlines met | {_met(d)} | {_met(b)} | |",
        f"| Chat p95 (worst in window) | {_f(d.chat_p95_during_s, '.2f', ' s')} | "
        f"{_f(b.chat_p95_during_s, '.2f', ' s')} | |", ""]
    caps = {c for c in (cap_d, cap_b) if c is not None}
    if caps:
        lines += [f"Cap: {', '.join(f'{c:.1f} W' for c in sorted(caps))} "
                  "(from each run's event; the dispatched run's cap where the baseline logged none).", ""]
    notes = [f"- {label}: {s}" for label, _, r, _ in rows for s in r.shortfalls]
    if notes:
        lines += ["## Shortfalls and caveats", ""] + notes + [""]
    return "\n".join(lines)


def chart(rows, out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 3.6))
    for (label, run, rep, _), color in zip(rows, ("#1f6feb", "#bc4c00")):
        s = run.watts(rep.window_start, rep.window_end)
        ax.plot([t - rep.window_start for t, _ in s], [w for _, w in s], lw=1.2, color=color,
                label=f"{label} ({rep.run_id})")
    cap = rows[0][3]
    if cap is not None:
        ax.axhline(cap, ls="--", color="#cf222e", label=f"cap {cap:.1f} W")
    ax.set_xlabel("seconds from window start")
    ax.set_ylabel("measured W (powermetrics)")
    ax.set_title("Dispatched vs baseline: measured SoC power")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dispatched", help="run id or timeline path (default: newest dispatcher run)")
    ap.add_argument("--baseline", help="run id or timeline path (default: newest baseline run)")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    d = resolve(a.dispatched)[0] if a.dispatched else newest("dispatcher")
    b = resolve(a.baseline)[0] if a.baseline else newest("baseline")
    rows, span = compare(d, b)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"compare-{rows[0][2].run_id}-vs-{rows[1][2].run_id}"
    png = chart(rows, out / f"{name}.png")
    md = out / f"{name}.md"
    md.write_text(table(rows, span) + f"\n![measured power]({png.name})\n", encoding="utf-8")
    print(md.read_text(encoding="utf-8"))
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
