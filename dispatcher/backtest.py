"""Backtest: the same jobs, at this Mac's measured watts, scheduled on real past days of grid prices and fuel mix.

    uv run python -m dispatcher.backtest --pull --days 14    # fetch real days once (gridstatus, keyless); commits
    uv run python -m dispatcher.backtest                     # rerun offline from docs/evidence/backtest/*.csv

Each day the jobs arrive at `arrive_hour` (09:00 local) and are due 24 h later: a training job and a batch job
needing the GPU hours below, chat always on at a light measured load. Two plans for the same work:
  - run now: every job starts on the GPU when it arrives and runs until done (what a cluster does by default);
  - Brownout: the CP-SAT dispatcher (dispatcher/solve.py), the same code that runs on the Mac, per objective.
Each plan is priced at that day's real day-ahead prices and carbon from its real hourly fuel mix (config/isos.yaml
factors). Watts are the measured calibration (docs/evidence/calibration.json), not estimates; what is modelled is
which slot each job runs in. Prices and carbon come from the ISO's own published data via gridstatus.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean, median
from zoneinfo import ZoneInfo

import pandas as pd

from core import config
from core.types import Calibration, GridSignal, Job

from .solve import load_policy, solve

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "evidence" / "backtest"
CAL = ROOT / "docs" / "evidence" / "calibration.json"
SETUP = {"arrive_hour": 9, "horizon_h": 24, "train_gpu_h": 6.0, "batch_gpu_h": 3.0, "chat_busy": 0.25,
         "objectives": ["cost", "carbon", "balanced"]}
LOCATION = {"CAISO": "TH_SP15_GEN-APND", "ERCOT": "HB_HOUSTON"}


# ------------------------------------------------------------------------------------------------ data
def pull(iso: str, days: int, end: datetime | None = None) -> Path:
    """Hourly day-ahead price at the hub and hourly carbon from the 5-min fuel mix, for `days` days plus the next
    (each day's jobs run past midnight). One CSV per ISO, with the source in its header."""
    from grid import isos
    from grid.carbon import intensity_gco2_per_kwh
    tz = ZoneInfo(config.isos["isos"][iso]["timezone"])
    end = (end or datetime.now(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    prices = isos.fetch_prices(iso, "DAY_AHEAD_HOURLY", [LOCATION[iso]], date=pd.Timestamp(start), end=pd.Timestamp(end))
    prices["hour"] = pd.to_datetime(prices["interval_start"], utc=True).dt.tz_convert(tz).dt.floor("h")
    factors = config.isos["emission_factors_gco2_per_kwh"]
    carbon = {}
    for i in range(days):
        day = start + timedelta(days=i)
        try:
            mix = isos.fetch_fuel_mix(iso, pd.Timestamp(day.date()))
        except Exception as e:                         # ERCOT: gridstatus serves only today's fuel mix
            print(f"{iso} {day:%Y-%m-%d}: no historical fuel mix ({type(e).__name__}); carbon left empty")
            continue
        mix["hour"] = pd.to_datetime(mix["interval_start"], utc=True).dt.tz_convert(tz).dt.floor("h")
        for hour, g in mix.drop(columns=["interval_start"]).groupby("hour"):
            carbon[hour] = intensity_gco2_per_kwh(g.drop(columns=["hour"]).mean().to_dict(), factors)[0]
    rows = (prices.groupby("hour")["price"].mean().rename("price_usd_mwh").to_frame()
            .join(pd.Series(carbon, name="carbon_g_kwh", dtype=float), how="left").reset_index())
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"{iso}.csv"
    with out.open("w") as f:
        carbon_note = ("hourly carbon intensity from its 5-min fuel mix (config/isos.yaml factors)" if carbon
                       else "no carbon: gridstatus serves no past-day fuel mix for this ISO")
        f.write(f"# REAL data: {iso} day-ahead hourly LMP/SPP at {LOCATION[iso]} and {carbon_note}, via gridstatus, "
                f"pulled {datetime.now(tz):%Y-%m-%d %H:%M %Z}.\n")
        rows.to_csv(f, index=False)
    return out


def load_days(iso: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{iso}.csv", comment="#")
    df["hour"] = pd.to_datetime(df["hour"], utc=True).dt.tz_convert(config.isos["isos"][iso]["timezone"])
    return df.set_index("hour").sort_index()


# ------------------------------------------------------------------------------------------------ one day
def _jobs(arrive: datetime, cal: Calibration) -> list[Job]:
    due = arrive + timedelta(hours=SETUP["horizon_h"])
    return [Job(id="chat", kind="interactive", owner="ops", priority=1, interruptible=False, device="gpu",
                min_concurrency=1, max_concurrency=4),
            Job(id="train", kind="deferrable", owner="ml-team", priority=2, device="either", deadline=due,
                required_runtime_min=round(60 * SETUP["train_gpu_h"])),
            Job(id="batch", kind="droppable", owner="data-eng", priority=3, device="either", deadline=due,
                required_runtime_min=round(60 * SETUP["batch_gpu_h"]))]


def _signal(iso: str, day: pd.DataFrame, slots: list[datetime], with_carbon: bool) -> GridSignal:
    price = [(s, float(day.loc[pd.Timestamp(s).floor("h"), "price_usd_mwh"])) for s in slots]
    carbon = [(s, float(day.loc[pd.Timestamp(s).floor("h"), "carbon_g_kwh"])) for s in slots] if with_carbon else []
    return GridSignal(iso=iso, location=LOCATION[iso], t=slots[0].timestamp(), price_now=price[0][1],
                      price_curve=price, carbon_curve=carbon, price_curve_source="DAY_AHEAD_HOURLY (backtest)")


def _priced(watts: list[float], slots: list[datetime], day: pd.DataFrame, slot_h: float) -> tuple[float, float | None, float]:
    """($, gCO2, Wh) of a plan's per-slot watts at that day's real hourly price and carbon (None without carbon)."""
    usd = g = wh = 0.0
    has_carbon = bool(day["carbon_g_kwh"].notna().all())
    for w, s in zip(watts, slots):
        row = day.loc[pd.Timestamp(s).floor("h")]
        e_kwh = w * slot_h / 1000
        usd += e_kwh / 1000 * float(row["price_usd_mwh"])
        g += e_kwh * float(row["carbon_g_kwh"]) if has_carbon else 0.0
        wh += e_kwh * 1000
    return usd, (g if has_carbon else None), wh


def run_now_watts(jobs: list[Job], cal: Calibration, n: int, slot_min: int) -> list[float]:
    """Every deferrable job on the GPU from arrival until its GPU time is done; chat always on."""
    from .model import chat_w
    chat = next(j for j in jobs if j.kind == "interactive")
    w = [cal.idle_w + chat_w(chat, cal, SETUP["chat_busy"])] * n
    for j in jobs:
        if j.kind == "interactive":
            continue
        for s in range(min(n, math.ceil(j.required_runtime_min / slot_min))):
            w[s] += cal.jobs[j.id]["gpu"].delta_w
    return w


def backtest_day(iso: str, data: pd.DataFrame, date, cal: Calibration) -> dict | None:
    tz = ZoneInfo(config.isos["isos"][iso]["timezone"])
    arrive = datetime(date.year, date.month, date.day, SETUP["arrive_hour"], tzinfo=tz)
    slot_min = int(config.policy.get("slot_minutes", 15))
    n = SETUP["horizon_h"] * 60 // slot_min
    slots = [arrive + timedelta(minutes=slot_min * i) for i in range(n)]
    hours = {pd.Timestamp(s).floor("h") for s in slots}
    if not hours <= set(data.index):
        return None                                   # a missing hour: skip the day rather than invent one
    day = data.loc[sorted(hours)]
    jobs, slot_h = _jobs(arrive, cal), slot_min / 60
    out = {"iso": iso, "date": str(date), "run_now": dict(zip(("usd", "g", "wh"), _priced(run_now_watts(jobs, cal, n, slot_min), slots, day, slot_h))),
           "deferrable_mwh": sum(j.required_runtime_min / 60 * cal.jobs[j.id]["gpu"].delta_w for j in jobs
                                 if j.kind != "interactive") / 1e6}
    with_carbon = bool(day["carbon_g_kwh"].notna().all())
    sig = _signal(iso, day, slots, with_carbon)
    for obj in (SETUP["objectives"] if with_carbon else ["cost"]):
        sched = solve(sig, _jobs(arrive, cal), load_policy({"objective": obj}), cal, chat_busy=SETUP["chat_busy"])
        usd, g, wh = _priced(sched.planned_w, slots, day, slot_h)
        out[obj] = {"usd": usd, "g": g, "wh": wh, "deadlines_met": not sched.deadline_misses,
                    "status": sched.solver_status}
    return out


# ------------------------------------------------------------------------------------------------ all days
def run(isos: list[str]) -> dict:
    cal = Calibration.model_validate_json(CAL.read_text())
    days = []
    for iso in isos:
        data = load_days(iso)
        for date in sorted({h.date() for h in data.index}):
            r = backtest_day(iso, data, date, cal)
            if r:
                days.append(r)
    return {"setup": SETUP, "calibration": {"measured_at": cal.measured_at, "machine": cal.machine}, "days": days,
            "summary": summarize(days)}


def summarize(days: list[dict]) -> dict:
    out = {}
    for iso in sorted({d["iso"] for d in days}):
        ds = [d for d in days if d["iso"] == iso]
        out[iso] = {"days": len(ds), "first": ds[0]["date"], "last": ds[-1]["date"]}
        for obj in SETUP["objectives"]:
            ok = [d for d in ds if obj in d]
            if not ok:
                continue
            cost = [100 * (1 - d[obj]["usd"] / d["run_now"]["usd"]) for d in ok if d["run_now"]["usd"] > 0]
            co2 = [100 * (1 - d[obj]["g"] / d["run_now"]["g"]) for d in ok if d[obj]["g"] is not None and d["run_now"]["g"]]
            out[iso][obj] = {"days": len(ok), "cost_saved_pct_median": median(cost) if cost else None,
                             "cost_saved_pct_mean": fmean(cost) if cost else None,
                             "co2_saved_pct_median": median(co2) if co2 else None,
                             "co2_saved_pct_mean": fmean(co2) if co2 else None,
                             "usd_saved_per_mwh_shifted": _per_mwh(ok, obj),
                             "deadlines_met": sum(d[obj]["deadlines_met"] for d in ok)}
    return out


def _per_mwh(days: list[dict], obj: str) -> float:
    """Dollars saved per MWh of the day's deferrable work (training + batch at measured GPU watts): the number that
    scales from this Mac to a campus. Same energy in both plans except device choice; the price paid differs."""
    saved = sum(d["run_now"]["usd"] - d[obj]["usd"] for d in days)
    mwh = sum(d["deferrable_mwh"] for d in days)
    return saved / mwh if mwh else 0.0


def render(result: dict) -> str:
    s = result["setup"]
    lines = ["# Backtest: Brownout vs run-now on real grid days", "",
             f"Jobs arrive at {s['arrive_hour']:02d}:00 local and are due {s['horizon_h']} h later: training "
             f"{s['train_gpu_h']:g} GPU-hours, batch {s['batch_gpu_h']:g} GPU-hours, chat always on at "
             f"{s['chat_busy']:g} busy streams. Watts: this Mac's measured calibration ({result['calibration']['machine']}). "
             "Prices: the ISO's day-ahead hourly price at its hub; carbon: the hour's real fuel mix. Regenerate with "
             "`uv run python -m dispatcher.backtest` (offline, from docs/evidence/backtest/*.csv).", ""]
    for iso, x in result["summary"].items():
        lines += [f"## {iso}: {x['days']} days, {x['first']} to {x['last']}", "",
                  "| Brownout objective | Energy cost saved vs run-now (median, mean) | Carbon saved (median, mean) | Deadlines met |",
                  "|---|---:|---:|---:|"]
        fmt = lambda v: "n/a" if v is None else f"{v:.1f} %"
        for obj in s["objectives"]:
            if obj not in x:
                continue
            o = x[obj]
            lines.append(f"| {obj} | {fmt(o['cost_saved_pct_median'])}, {fmt(o['cost_saved_pct_mean'])} | "
                         f"{fmt(o['co2_saved_pct_median'])}, {fmt(o['co2_saved_pct_mean'])} | {o['deadlines_met']}/{o['days']} |")
        if "carbon" not in x:
            lines.append(f"\nCarbon n/a for {iso}: gridstatus serves only today's {iso} fuel mix, so past days have no hourly carbon; cost only.")
        lines += ["", f"Saved per MWh of deferrable work shifted (cost objective): ${x['cost']['usd_saved_per_mwh_shifted']:.2f}/MWh.", ""]
    lines += ["## Every day", "", "| ISO | Day | Run-now $ | Cost-objective $ | Run-now gCO2 | Carbon-objective gCO2 |",
              "|---|---|---:|---:|---:|---:|"]
    for d in result["days"]:
        g = lambda v: "n/a" if v is None else f"{v:.1f}"
        lines.append(f"| {d['iso']} | {d['date']} | {d['run_now']['usd']:.6f} | {d['cost']['usd']:.6f} | "
                     f"{g(d['run_now']['g'])} | {g(d['carbon']['g']) if 'carbon' in d else 'n/a'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pull", action="store_true", help="fetch real days first (network)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--iso", nargs="*", default=["CAISO", "ERCOT"])
    a = ap.parse_args(argv)
    if a.pull:
        for iso in a.iso:
            print(f"pulled {pull(iso, a.days + 1)}")
    result = run(a.iso)
    (DATA / "result.json").write_text(json.dumps(result, indent=1, default=str))
    md = ROOT / "docs" / "evidence" / "backtest.md"
    md.write_text(render(result))
    print(md.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
