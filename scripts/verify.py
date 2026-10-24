"""Recompute every published number from the raw measured timelines, and check the pages that quote them.

    make verify                  # check: no Mac, no sudo, no network; exit 1 on any mismatch
    make verify ARGS=--write     # also re-render docs/evidence/*.md and charts from the raw timelines

The raw timelines are what the runs logged, second by second (powermetrics watts, every plan, every knob action,
every approval), committed gzipped under docs/evidence/runs/<run id>/timeline.jsonl.gz. Every claim, the value a
page states and where, is in docs/evidence/claims.yaml. This script recomputes each value with the same reporter
the runs used (agent/reporter.py) and checks (1) it matches the claim at the claim's precision, and (2) each page
listed under `quoted_in` still contains the quoted text. CI runs it on every push (tests/test_verify.py).
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.reporter import Run, build_report, compare_runs, share_under  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence"
CLAIMS = EVIDENCE / "claims.yaml"


def timeline(run_id: str) -> Path:
    p = EVIDENCE / "runs" / run_id / "timeline.jsonl.gz"
    if not p.is_file():
        raise FileNotFoundError(f"no committed timeline for run {run_id} at {p.relative_to(ROOT)}")
    return p


def _report_metrics(run: Run, rep, cap: float | None) -> dict[str, float | None]:
    under = share_under(run, rep.window_start, rep.window_end, cap)
    return {"mean_w": rep.event_w, "baseline_w": rep.baseline_w, "reduction_pct": rep.reduction_pct,
            "time_to_compliance_s": rep.time_to_compliance_s, "under_cap_pct": None if under is None else 100 * under,
            "chat_ttft_before_s": rep.chat_p95_before_s, "chat_ttft_during_s": rep.chat_p95_during_s,
            "train_steps": rep.work_done.get("train"), "window_s": rep.window_end - rep.window_start}


def comparison_metrics(dispatched: str, baseline: str) -> dict[str, float | None]:
    paths = {"dispatched": timeline(dispatched), "baseline": timeline(baseline)}
    c = compare_runs(paths["dispatched"], paths["baseline"])
    runs = {k: Run.load(p) for k, p in paths.items()}
    cap = runs["dispatched"].cap_w if runs["dispatched"].cap_w is not None else runs["baseline"].cap_w
    out: dict[str, float | None] = {"cap_w": cap}
    for k, rep in (("dispatched", c.dispatched), ("baseline", c.baseline)):
        out.update({f"{k}.{m}": v for m, v in _report_metrics(runs[k], rep, cap).items()})
    return out


def report_metrics(run_id: str) -> dict[str, float | None]:
    path = timeline(run_id)
    run = Run.load(path)
    rep = build_report(path)
    return {"cap_w": run.cap_w, **_report_metrics(run, rep, run.cap_w)}


def matches(expected, got) -> bool:
    """At the claim's own precision: 14.34 means 14.335 <= x < 14.345; 93 means 92.5 <= x < 93.5; null means none."""
    if expected is None:
        return got is None
    if got is None:
        return False
    places = max(0, -Decimal(str(expected)).as_tuple().exponent)
    return round(float(got), places) == round(float(expected), places)


def check(claims: dict, root: Path = ROOT) -> list[tuple[str, str, object, object, bool]]:
    """(claim, metric, expected, recomputed, ok) for every number; quotes appear as metric `quoted in <file>`."""
    rows = []
    for c in claims.get("comparisons", []) + claims.get("reports", []):
        got = (comparison_metrics(c["dispatched"], c["baseline"]) if "dispatched" in c else report_metrics(c["run"]))
        for metric, want in c["expect"].items():
            if metric not in got:
                raise KeyError(f"{c['name']}: unknown metric {metric!r} (have {sorted(got)})")
            rows.append((c["name"], metric, want, got[metric], matches(want, got[metric])))
        for page, quotes in (c.get("quoted_in") or {}).items():
            text = (root / page).read_text(encoding="utf-8")
            for q in quotes:
                rows.append((c["name"], f"quoted in {page}", q, q if q in text else None, q in text))
    return rows


def write_reports(claims: dict) -> list[Path]:
    """Re-render the published reports from the raw timelines (same code, repo-relative paths)."""
    from agent import reporter
    from scripts import compare
    out = []
    for c in claims.get("reports", []):
        out.append(reporter.write(timeline(c["run"]), EVIDENCE))
    for c in claims.get("comparisons", []):
        out.append(compare.write(timeline(c["dispatched"]), timeline(c["baseline"]), EVIDENCE))
    return out


def _fmt(v) -> str:
    return "none" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="also re-render docs/evidence reports from the timelines")
    a = ap.parse_args(argv)
    claims = yaml.safe_load(CLAIMS.read_text(encoding="utf-8"))
    rows = check(claims)
    width = max(len(m) for _, m, *_ in rows)
    last = None
    for name, metric, want, got, ok in rows:
        if name != last:
            print(f"\n{name}")
            last = name
        print(f"  {'ok  ' if ok else 'FAIL'} {metric:<{width}}  claimed {_fmt(want):>10}  recomputed {_fmt(got)}")
    bad = [r for r in rows if not r[4]]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} checks pass, from {len(list((EVIDENCE / 'runs').glob('*/timeline.jsonl.gz')))} "
          f"raw timelines in docs/evidence/runs/")
    if a.write:
        for p in write_reports(claims):
            print(f"wrote {p.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
