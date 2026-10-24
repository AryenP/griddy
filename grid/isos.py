"""Adapters from gridstatus to tidy frames. One function per feed. Every function returns a
DataFrame in a fixed shape so the watcher never looks at ISO-specific column names.

Shapes:
  prices:   interval_start (tz-aware), location, price ($/MWh)
  forecast: interval_start, load_mw
  fuel mix: interval_start, <one column per source, MW>
"""
from __future__ import annotations

import pandas as pd

import gridstatus

_CLIENTS = {"CAISO": gridstatus.CAISO, "ERCOT": gridstatus.Ercot, "PJM": gridstatus.PJM}
_SOURCE_URLS = {
    "CAISO": "https://oasis.caiso.com/oasisapi",
    "ERCOT": "https://www.ercot.com/mp/data-products",
    "PJM": "https://dataminer2.pjm.com",
}


def source_url(iso: str) -> str:
    return _SOURCE_URLS[iso]


def _client(iso: str):
    if iso == "PJM":
        from core.config import settings
        return gridstatus.PJM(api_key=settings.pjm_api_key)
    return _CLIENTS[iso]()


def _tidy_prices(df: pd.DataFrame) -> pd.DataFrame:
    col = "LMP" if "LMP" in df.columns else "SPP"
    out = df[["Interval Start", "Location", col]].rename(
        columns={"Interval Start": "interval_start", "Location": "location", col: "price"}
    )
    return out.sort_values("interval_start").reset_index(drop=True)


def fetch_prices(iso: str, market: str, locations: list[str], date="today", end=None) -> pd.DataFrame:
    c = _client(iso)
    if iso == "ERCOT":
        df = c.get_spp(date=date, end=end, market=market, location_type="Trading Hub")
        df = df[df["Location"].isin(locations)]
    elif iso == "PJM":
        df = c.get_lmp(date=date, end=end, market=market, locations=locations)
    else:
        df = c.get_lmp(date=date, end=end, market=market, locations=locations)
    return _tidy_prices(df)


def fetch_day_ahead(iso: str, market: str, locations: list[str]) -> pd.DataFrame:
    """Today and tomorrow where published (CAISO/ERCOT publish tomorrow's DAM by ~1 PM)."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    return fetch_prices(iso, market, locations, date=today - pd.Timedelta(days=1),
                        end=today + pd.Timedelta(days=2))


def fetch_load_forecast(iso: str) -> pd.DataFrame:
    df = _client(iso).get_load_forecast("today")
    col = "Load Forecast" if "Load Forecast" in df.columns else "System Total"   # CAISO | ERCOT
    out = df[["Interval Start", col]].rename(columns={"Interval Start": "interval_start", col: "load_mw"})
    out = out.groupby("interval_start", as_index=False).last()   # ERCOT republishes hourly; keep newest
    return out.sort_values("interval_start").reset_index(drop=True)


def fetch_fuel_mix(iso: str, date="today") -> pd.DataFrame:
    df = _client(iso).get_fuel_mix(date)
    if "Interval Start" not in df.columns:      # ERCOT has only `Time`
        df = df.rename(columns={"Time": "Interval Start"})
    drop = [c for c in ("Time", "Interval End") if c in df.columns]
    out = df.drop(columns=drop).rename(columns={"Interval Start": "interval_start"})
    return out.sort_values("interval_start").reset_index(drop=True)


def fetch_ercot_conditions() -> dict:
    row = gridstatus.Ercot().get_real_time_system_conditions().iloc[-1]
    return {k: (v.isoformat() if hasattr(v, "isoformat") else float(v)) for k, v in row.items()
            if v == v}  # drop NaN
