"""Grid signal from a saved REAL CAISO pull (tests/fixtures, labelled). No synthetic grid data."""
from pathlib import Path

import pandas as pd
import pytest

from core.types import GridSignal
from grid.carbon import intensity_gco2_per_kwh
from grid.watcher import signal_from_frames, slot_starts

FIX = Path(__file__).parent / "fixtures"


def _csv(name, tz_cols=("interval_start",)):
    df = pd.read_csv(FIX / f"{name}.csv", comment="#")
    for c in tz_cols:
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


@pytest.fixture
def frames():
    return dict(rt=_csv("caiso_rt_lmp"), da=_csv("caiso_day_ahead"),
                load=_csv("caiso_load_forecast"), fuel=_csv("caiso_fuel_mix"))


def test_signal_from_real_pull(frames):
    rt = frames["rt"]
    last = rt[rt.location == "TH_SP15_GEN-APND"].iloc[-1]
    now = pd.Timestamp(last.interval_start).timestamp() + 60
    sig = signal_from_frames(iso="CAISO", location="TH_SP15_GEN-APND", **frames, alerts=[],
                             fetched_at=now - 10, now=now, slot_minutes=15, horizon_hours=24,
                             poll_lmp_s=300, tz="US/Pacific")
    assert isinstance(sig, GridSignal)
    assert sig.price_now == pytest.approx(float(last.price))
    assert len(sig.price_curve) == 96
    assert sig.feed_age_s == pytest.approx(10) and not sig.stale
    # the day-ahead hourly price for the first slot's hour is what the curve carries
    da = frames["da"]
    hour = pd.Timestamp(sig.price_curve[0][0]).tz_convert("UTC").floor("h")
    expect = float(da[(da.location == "TH_SP15_GEN-APND") & (da.interval_start == hour)].price.iloc[0])
    assert sig.price_curve[0][1] == pytest.approx(expect)
    assert sig.carbon_now is not None and 0 < sig.carbon_now < 820
    assert sig.carbon_curve_is_proxy
    assert sig.source_urls and sig.price_interval_start is not None


def test_stale_flag(frames):
    last = frames["rt"].iloc[-1]
    now = pd.Timestamp(last.interval_start).timestamp() + 3600
    sig = signal_from_frames(iso="CAISO", location="TH_SP15_GEN-APND", **frames, alerts=[],
                             fetched_at=now - 700, now=now, slot_minutes=15, horizon_hours=24,
                             poll_lmp_s=300, tz="US/Pacific")
    assert sig.stale


def test_slots_align_to_quarter_hours():
    t = pd.Timestamp("2026-10-23 21:47:13-07:00").to_pydatetime()
    s = slot_starts(t, 15, 24)
    assert len(s) == 96 and s[0].minute == 45 and s[0].second == 0 and s[-1] - s[0] == pd.Timedelta(hours=23, minutes=45)


def test_carbon_excludes_negative_and_unknown():
    g, detail = intensity_gco2_per_kwh({"Natural Gas": 100, "Solar": -5, "Nuclear": 100, "Mystery": 50},
                                       {"Natural Gas": 410, "Solar": 41, "Nuclear": 12})
    assert g == pytest.approx((410 + 12) / 2)
    assert set(detail) == {"Natural Gas", "Nuclear"}

