"""The event's hours, fetched live from the U.S. EIA's Open Data API when a judge presses play (Aryen, Sat evening: "it's
really important that the software is getting the data live").

api.eia.gov v2 serves the same EIA-930 numbers as the six-month files in docs/evidence/events/ (hour-ending UTC; checked
equal for Uri on Sat evening). The key is EIA_API_KEY from .env (free from eia.gov/opendata), else the public DEMO_KEY
(rate-limited by api.data.gov), so a fetch is reused for `refetch_s`. If the API cannot be reached the replay runs on the
evidence copy and the page says so.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

BASE = "https://api.eia.gov/v2/electricity/rto"
FUELS = {"COL": "Coal", "NG": "Natural Gas", "NUC": "Nuclear", "OIL": "All Petroleum Products",
         "WAT": "Hydropower and Pumped Storage", "SUN": "Solar", "WND": "Wind", "OTH": "Other Fuel Sources"}


def _get(path: str, params: list[tuple[str, str]], timeout: float) -> list[dict]:
    key = os.getenv("EIA_API_KEY") or "DEMO_KEY"
    rows, offset = [], 0
    while True:
        r = httpx.get(f"{BASE}/{path}/data/", params=[("api_key", key), *params, ("offset", str(offset)), ("length", "5000")],
                      timeout=timeout)
        r.raise_for_status()
        resp = r.json()["response"]
        rows += resp["data"]
        offset += len(resp["data"])
        if not resp["data"] or offset >= int(resp["total"]):
            return rows


def fetch(ev: dict, timeout: float = 8.0) -> tuple[pd.DataFrame, dict]:
    """The event's hours (the evidence file's span: two days either side of the window) as the evidence file's columns."""
    w0 = datetime.fromisoformat(ev["window"][0]) - timedelta(days=2)
    w1 = datetime.fromisoformat(ev["window"][1]) + timedelta(days=2)
    span = [("frequency", "hourly"), ("data[0]", "value"), ("facets[respondent][]", ev["ba"]),
            ("start", f"{w0:%Y-%m-%dT%H}"), ("end", f"{w1:%Y-%m-%dT%H}")]
    region = _get("region-data", span + [("facets[type][]", "D"), ("facets[type][]", "DF")], timeout)
    fuel = _get("fuel-type-data", span, timeout)
    cols: dict[str, dict[str, float]] = {}
    for r in region:
        cols.setdefault({"D": "demand_mw", "DF": "demand_forecast_mw"}[r["type"]], {})[r["period"]] = _num(r["value"])
    for r in fuel:
        if r["fueltype"] in FUELS:
            cols.setdefault(FUELS[r["fueltype"]], {})[r["period"]] = _num(r["value"])
    df = pd.DataFrame(cols).sort_index()
    df.insert(0, "utc_end", [f"{p}:00:00Z" for p in df.index])
    df = df.reset_index(drop=True)
    meta = {"source": "live", "fetched_at": datetime.now(timezone.utc).isoformat(), "rows": len(df),
            "url": f"{BASE}/region-data and /fuel-type-data, respondent {ev['ba']}, {w0:%Y-%m-%d} to {w1:%Y-%m-%d}",
            "key": "EIA_API_KEY" if os.getenv("EIA_API_KEY") else "DEMO_KEY (public, rate-limited)"}
    return df, meta


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def agreement(live: pd.DataFrame, evidence: pd.DataFrame) -> float | None:
    """The largest difference, in MW, between the live hours and the evidence copy over the hours both have."""
    a = live.set_index("utc_end")[["demand_mw", "demand_forecast_mw"]]
    b = evidence.set_index("utc_end")[["demand_mw", "demand_forecast_mw"]]
    both = a.join(b, rsuffix="_e", how="inner").dropna()
    if both.empty:
        return None
    return float(max((both["demand_mw"] - both["demand_mw_e"]).abs().max(),
                     (both["demand_forecast_mw"] - both["demand_forecast_mw_e"]).abs().max()))


class Cache:
    """One live fetch per event per `refetch_s`, so a demo day stays inside DEMO_KEY's limits."""

    def __init__(self, refetch_s: float = 600.0):
        self.refetch_s = refetch_s
        self.got: dict[str, tuple[float, pd.DataFrame, dict]] = {}

    def get(self, ev: dict, now: float | None = None):
        now = time.time() if now is None else now
        hit = self.got.get(ev["id"])
        if hit and now - hit[0] < self.refetch_s:
            return hit[1], {**hit[2], "reused": True}
        df, meta = fetch(ev)
        self.got[ev["id"]] = (now, df, meta)
        return df, meta
