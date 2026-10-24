"""Polls the ISO feeds on their own cadences and turns them into a GridSignal with its age.
Signal construction is a pure function of the fetched frames (`signal_from_frames`) so it is
testable against a saved real pull. Every refresh is logged as a `grid` timeline event.

    uv run python -m grid.watcher --once            # one signal, printed
    uv run python -m grid.watcher --duration 120    # poll, log to runs/<id>/timeline.jsonl
    uv run python -m grid.watcher --duration 120 --with-meter   # plus powermetrics (needs sudo)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from core.config import isos as ISOS_CFG
from core.config import policy as POLICY_CFG
from core.config import settings
from core.timeline import Timeline
from core.types import GridSignal

from . import isos
from .carbon import intensity_gco2_per_kwh

log = logging.getLogger("grid.watcher")


def slot_starts(now: datetime, slot_minutes: int, horizon_hours: int) -> list[datetime]:
    first = now.replace(second=0, microsecond=0)
    first -= timedelta(minutes=first.minute % slot_minutes)
    n = horizon_hours * 60 // slot_minutes
    return [first + timedelta(minutes=slot_minutes * i) for i in range(n)]


def _hourly_lookup(df: pd.DataFrame, value_col: str) -> dict[pd.Timestamp, float]:
    return {pd.Timestamp(r.interval_start).tz_convert("UTC"): float(getattr(r, value_col))
            for r in df.itertuples(index=False)}


def signal_from_frames(
    *, iso: str, location: str, rt: pd.DataFrame, da: pd.DataFrame | None,
    load: pd.DataFrame | None, fuel: pd.DataFrame | None, alerts: list[str],
    fetched_at: float, now: float, slot_minutes: int, horizon_hours: int, poll_lmp_s: int,
    tz: str,
) -> GridSignal:
    factors = ISOS_CFG["emission_factors_gco2_per_kwh"]
    here = rt[rt["location"] == location]
    if here.empty:
        raise ValueError(f"no real-time prices for {location}")
    last = here.iloc[-1]
    price_now = float(last["price"])
    price_interval_start = pd.Timestamp(last["interval_start"]).to_pydatetime()

    now_dt = datetime.fromtimestamp(now, tz=ZoneInfo(tz))   # slots in the ISO's local time
    slots = slot_starts(now_dt, slot_minutes, horizon_hours)

    da_lookup = _hourly_lookup(da[da["location"] == location], "price") if da is not None and not da.empty else {}
    price_curve, da_hits = [], 0
    for s in slots:
        hour = pd.Timestamp(s).tz_convert("UTC").floor("h")
        if hour in da_lookup:
            price_curve.append((s, da_lookup[hour])); da_hits += 1
        else:
            price_curve.append((s, price_now))
    if da_hits == len(slots):
        curve_source = "DAY_AHEAD_HOURLY"
    elif da_hits:
        curve_source = f"DAY_AHEAD_HOURLY for {da_hits}/{len(slots)} slots, last real-time price held flat after"
    else:
        curve_source = "last real-time price held flat (no day-ahead rows for the horizon)"

    load_curve = []
    if load is not None and not load.empty:
        load_curve = [(pd.Timestamp(r.interval_start).to_pydatetime(), float(r.load_mw))
                      for r in load.itertuples(index=False)]

    carbon_now, carbon_curve, mix, proxy = None, [], {}, False
    if fuel is not None and not fuel.empty:
        row = fuel.iloc[-1]
        mix = {k: float(v) for k, v in row.items() if k != "interval_start"}
        carbon_now, _ = intensity_gco2_per_kwh(mix, factors)
        carbon_curve = [(s, carbon_now) for s in slots]   # live mix held flat; labelled proxy
        proxy = True

    age = max(0.0, now - fetched_at)
    return GridSignal(
        iso=iso, location=location, t=now,
        price_now=price_now, price_interval_start=price_interval_start,
        price_curve=price_curve, price_curve_source=curve_source,
        load_forecast=load_curve,
        carbon_now=carbon_now, carbon_curve=carbon_curve, carbon_curve_is_proxy=proxy,
        fuel_mix_mw=mix, alerts=alerts, feed_age_s=age, stale=age > 2 * poll_lmp_s,
        source_urls=[isos.source_url(iso)],
    )


class GridWatcher:
    def __init__(self, iso: str, location: str, timeline: Timeline | None = None):
        cfg = ISOS_CFG["isos"][iso]
        self.iso, self.location, self.cfg, self.tl = iso, location, cfg, timeline
        self.locations = cfg["locations"] if isinstance(cfg["locations"], list) else [location]
        self.slot_minutes = int(POLICY_CFG.get("slot_minutes", 15))
        self.horizon_hours = int(POLICY_CFG.get("horizon_hours", 24))
        self.rt = self.da = self.load = self.fuel = None
        self.alerts: list[str] = []
        self.rt_fetched_at = 0.0
        self.subscribers: list = []
        self._signal: GridSignal | None = None

    # ---- fetches (blocking gridstatus calls, run in threads) ----
    async def refresh_rt(self):
        self.rt = await asyncio.to_thread(isos.fetch_prices, self.iso, self.cfg["lmp_market"], self.locations)
        self.rt_fetched_at = time.time()

    async def refresh_da(self):
        self.da = await asyncio.to_thread(isos.fetch_day_ahead, self.iso, self.cfg["day_ahead_market"], self.locations)

    async def refresh_load(self):
        self.load = await asyncio.to_thread(isos.fetch_load_forecast, self.iso)

    async def refresh_fuel(self):
        self.fuel = await asyncio.to_thread(isos.fetch_fuel_mix, self.iso)

    async def refresh_conditions(self):
        cond = await asyncio.to_thread(isos.fetch_ercot_conditions)
        rules = self.cfg.get("alert_rules", {})
        alerts = []
        f = cond.get("Current Frequency")
        if f is not None and "frequency_low_hz" in rules and f < rules["frequency_low_hz"]:
            alerts.append(f"ERCOT frequency {f:.3f} Hz below {rules['frequency_low_hz']} Hz")
        self.alerts = alerts
        if self.tl:
            self.tl.log("grid", iso=self.iso, feed="system_conditions", **cond)

    def signal(self) -> GridSignal:
        if self.rt is None:
            raise RuntimeError("no real-time prices yet")
        self._signal = signal_from_frames(
            iso=self.iso, location=self.location, rt=self.rt, da=self.da, load=self.load,
            fuel=self.fuel, alerts=self.alerts, fetched_at=self.rt_fetched_at, now=time.time(),
            slot_minutes=self.slot_minutes, horizon_hours=self.horizon_hours,
            poll_lmp_s=int(self.cfg["poll_s"]["lmp"]), tz=self.cfg["timezone"],
        )
        return self._signal

    @property
    def latest(self) -> GridSignal | None:
        return self._signal

    async def refresh_all(self) -> GridSignal:
        results = await asyncio.gather(self.refresh_rt(), self.refresh_da(), self.refresh_load(),
                                       self.refresh_fuel(), return_exceptions=True)
        for name, r in zip(("rt", "da", "load", "fuel"), results):
            if isinstance(r, Exception):
                log.warning("%s %s fetch failed: %r", self.iso, name, r)
                if self.tl:
                    self.tl.log("note", level="warning", feed=name, iso=self.iso, error=repr(r)[:300])
        if "system_conditions" in self.cfg["poll_s"]:
            try:
                await self.refresh_conditions()
            except Exception as e:  # feed down: keep going on last known alerts
                log.warning("conditions fetch failed: %r", e)
        return self._publish()

    def _publish(self) -> GridSignal:
        sig = self.signal()
        if self.tl:
            self.tl.log("grid", feed="signal", **sig.model_dump(mode="json"))
        for cb in list(self.subscribers):
            cb(sig)
        return sig

    async def _loop(self, name: str, fn, period_s: int):
        while True:
            await asyncio.sleep(period_s)
            try:
                await fn()
                self._publish()
            except Exception as e:
                log.warning("%s refresh failed: %r", name, e)
                if self.tl:
                    self.tl.log("note", level="warning", feed=name, iso=self.iso, error=repr(e)[:300])
                if self.rt is not None:
                    self._publish()   # re-publish so feed_age_s and `stale` keep moving

    async def run(self):
        """First pull of everything, then one loop per feed at its configured cadence."""
        await self.refresh_all()
        p = self.cfg["poll_s"]
        loops = [
            self._loop("rt", self.refresh_rt, p["lmp"]),
            self._loop("da", self.refresh_da, p["forecast"]),
            self._loop("load", self.refresh_load, p["forecast"]),
            self._loop("fuel", self.refresh_fuel, p["fuel_mix"]),
        ]
        if "system_conditions" in p:
            loops.append(self._loop("conditions", self.refresh_conditions, p["system_conditions"]))
        await asyncio.gather(*loops)


def describe(sig: GridSignal) -> str:
    lo = min(sig.price_curve, key=lambda x: x[1]); hi = max(sig.price_curve, key=lambda x: x[1])
    lines = [
        f"{sig.iso} {sig.location}  price now ${sig.price_now:.2f}/MWh  interval {sig.price_interval_start:%Y-%m-%d %H:%M %Z}",
        f"  feed age {sig.feed_age_s:.0f}s{'  STALE' if sig.stale else ''}   source {sig.source_urls[0]}",
        f"  24h curve ({len(sig.price_curve)} slots, {sig.price_curve_source}): min ${lo[1]:.2f} @ {lo[0]:%H:%M}, max ${hi[1]:.2f} @ {hi[0]:%H:%M}",
    ]
    if sig.carbon_now is not None:
        top = sorted(sig.fuel_mix_mw.items(), key=lambda kv: -kv[1])[:3]
        lines.append(f"  carbon now {sig.carbon_now:.0f} gCO2/kWh from live mix: " + ", ".join(f"{k} {v:.0f} MW" for k, v in top) + ("  (curve = now held flat, proxy)" if sig.carbon_curve_is_proxy else ""))
    if sig.load_forecast:
        pk = max(sig.load_forecast, key=lambda x: x[1])
        lines.append(f"  load forecast peak {pk[1]:,.0f} MW @ {pk[0]:%H:%M}")
    if sig.alerts:
        lines.append("  ALERTS: " + "; ".join(sig.alerts))
    return "\n".join(lines)


async def _main(args):
    tl = None if args.once else Timeline()
    w = GridWatcher(args.iso, args.location, tl)
    if args.once:
        print(describe(await w.refresh_all()))
        return
    meter = None
    if args.with_meter:
        from meter.powermetrics import PowerMeter
        meter = PowerMeter(tl)
        await meter.start()
    w.subscribers.append(lambda s: print(describe(s)))
    print(f"timeline: {tl.path}")
    try:
        await asyncio.wait_for(w.run(), timeout=args.duration)
    except asyncio.TimeoutError:
        pass
    finally:
        if meter:
            await meter.stop()
        tl.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--iso", default=settings.iso)
    ap.add_argument("--location", default=settings.location)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--duration", type=int, default=120)
    ap.add_argument("--with-meter", action="store_true")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(ap.parse_args()))
