"""Facts about a solved schedule, derived from the solution and its inputs only. The LLM may
reword these; it may not invent them. Also the plain-text table `make solve` prints."""
from __future__ import annotations

from datetime import datetime

from core.types import Calibration, GridSignal, Job, Schedule


def _ranges(idx: list[int], slots, slot_minutes: int) -> str:
    if not idx:
        return "none"
    out, start, prev = [], idx[0], idx[0]
    for i in idx[1:] + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        end = slots[prev].timestamp() + slot_minutes * 60
        out.append(f"{slots[start]:%a %H:%M}-{datetime.fromtimestamp(end, tz=slots[0].tzinfo):%H:%M}")
        if i is not None:
            start = prev = i
    return ", ".join(out)


def explain(s: Schedule, sig: GridSignal, jobs: list[Job], deadline_slot: dict[str, int]) -> list[str]:
    prices = [p for _, p in sig.price_curve]
    carb = [c for _, c in sig.carbon_curve] if sig.carbon_curve else None
    facts = []
    for j in jobs:
        a = s.assignments[j.id]
        if j.kind == "interactive":
            reduced = [i for i, x in enumerate(a) if x.concurrency < j.max_concurrency]
            if reduced:
                facts.append(f"{j.id} held below max concurrency {j.max_concurrency} in {len(reduced)} slot(s) "
                             f"({_ranges(reduced, s.slots, s.slot_minutes)}) because the power cap binds there")
            else:
                facts.append(f"{j.id} runs in every slot at concurrency {j.max_concurrency} (never paused)")
            if s.chat_busy_streams is None:
                facts.append(f"{j.id} power planned for full concurrency (no traffic measured yet)")
            else:
                facts.append(f"{j.id} power planned at measured traffic: {s.chat_busy_streams:.2f} stream(s) busy "
                             f"on average over the last 60 s, held flat (re-solved when traffic changes)")
            continue
        on = [i for i, x in enumerate(a) if x.run]
        window = range(min(deadline_slot[j.id], len(a)))
        capped_off = [i for i in window if not a[i].run and s.caps_w[i] is not None]
        price_off = [i for i in window if not a[i].run and s.caps_w[i] is None]
        if not on:
            facts.append(f"{j.id}: no slots scheduled")
            continue
        p_on = sum(prices[i] for i in on) / len(on)
        line = f"{j.id} runs {len(on)} slot(s) {_ranges(on, s.slots, s.slot_minutes)} at avg ${p_on:.2f}/MWh"
        if price_off:
            p_off = sum(prices[i] for i in price_off) / len(price_off)
            line += f" vs ${p_off:.2f}/MWh avg over the {len(price_off)} uncapped slot(s) it skipped"
        devs = sorted({x.device for x in a if x.run})
        line += f"; device {'/'.join(devs)}"
        facts.append(line)
        if capped_off:
            facts.append(f"{j.id} paused in {len(capped_off)} capped slot(s) "
                         f"({_ranges(capped_off, s.slots, s.slot_minutes)}): it does not fit under the cap")
    capped = [i for i, c in enumerate(s.caps_w) if c is not None]
    if capped:
        head = max(s.caps_w[i] - s.planned_w[i] for i in capped)
        facts.append(f"power cap active in {len(capped)} slot(s) ({_ranges(capped, s.slots, s.slot_minutes)}); "
                     f"planned power stays under it with at most {head:.2f} W to spare")
    for sf in s.shortfalls:
        facts.append(f"shortfall: {sf.message}")
    if s.on_stale_data:
        facts.append(f"grid feed is {sig.feed_age_s:.0f}s old: plan is on last known data")
    if carb and sig.carbon_curve_is_proxy:
        facts.append("carbon curve is the live mix held flat (proxy); only price varies across slots")
    return facts


def render(s: Schedule, sig: GridSignal, jobs: list[Job], cal: Calibration) -> str:
    ids = [j.id for j in jobs]
    hdr = (f"Schedule {s.id}  solved {s.solver_status} in {s.solve_wall_s:.2f}s  "
           f"objective {s.objective_value:,.0f}\n"
           f"Grid: {sig.iso} {sig.location} now ${sig.price_now:.2f}/MWh (interval {sig.price_interval_start:%H:%M %Z}, "
           f"age {sig.feed_age_s:.0f}s{', STALE' if sig.stale else ''})  curve: {sig.price_curve_source}\n"
           f"Watts: idle {cal.idle_w:.2f} W measured {cal.window_s}s windows by powermetrics; job deltas from make calibrate\n")
    cols = "  ".join(f"{i:>9}" for i in ids)
    lines = [hdr, f"{'slots':<23} {'$/MWh':>7} {'gCO2':>5}  {cols}  {'plan W':>7} {'cap':>6}"]
    prices = [p for _, p in sig.price_curve]
    carb = [c for _, c in sig.carbon_curve] if sig.carbon_curve else [0.0] * len(prices)

    def cell(jid, i):
        a = s.assignments[jid][i]
        if not a.run:
            return "-"
        return f"c={a.concurrency}" if next(j for j in jobs if j.id == jid).kind == "interactive" else a.device

    rows, i = [], 0
    while i < len(prices):
        k = i
        key = lambda n: (tuple(cell(j, n) for j in ids), round(prices[n], 2), s.caps_w[n])
        while k + 1 < len(prices) and key(k + 1) == key(i):
            k += 1
        span = f"{s.slots[i]:%a %H:%M}" + (f"-{s.slots[k]:%H:%M}" if k > i else "")
        cap = "" if s.caps_w[i] is None else f"{s.caps_w[i]:.1f}"
        rows.append(f"{span:<23} {prices[i]:>7.2f} {carb[i]:>5.0f}  "
                    + "  ".join(f"{cell(j, i):>9}" for j in ids) + f"  {s.planned_w[i]:>7.2f} {cap:>6}")
        i = k + 1
    lines += rows
    lines.append(f"\nPlanned 24 h: ${s.cost_usd:.4f}, {s.co2_g:.1f} gCO2 (planned from calibrated watts; measured comes from the run)")
    if s.deadline_misses:
        lines.append("Deadline misses: " + "; ".join(f"{m.job_id} by {m.slip_min} min" for m in s.deadline_misses))
    lines.append("Why:")
    lines += [f"  - {f}" for f in s.explanations]
    return "\n".join(lines)
