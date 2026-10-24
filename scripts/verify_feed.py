"""Cross-check a run's logged CAISO prices against OASIS directly (raw HTTP, not gridstatus).

    uv run python scripts/verify_feed.py [runs/<id>/timeline.jsonl]
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone

import httpx

from core.timeline import Timeline

OASIS = "https://oasis.caiso.com/oasisapi/SingleZip"


def oasis_lmp(node: str, start: datetime) -> float:
    t0 = start.astimezone(timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    r = httpx.get(OASIS, timeout=60, params={
        "resultformat": 6, "queryname": "PRC_INTVL_LMP", "version": 3, "market_run_id": "RTM",
        "node": node, "startdatetime": t0.strftime("%Y%m%dT%H:%M-0000"),
        "enddatetime": t1.strftime("%Y%m%dT%H:%M-0000")})
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]))))
    for row in rows:
        if row["LMP_TYPE"] == "LMP" and row["INTERVALSTARTTIME_GMT"].startswith(t0.strftime("%Y-%m-%dT%H:%M")):
            return float(row["VALUE"])
    raise LookupError(f"OASIS has no LMP row for {node} at {t0:%Y-%m-%dT%H:%MZ}")


def main(path: str):
    seen = {}
    for ev in Timeline.read(path):
        d = ev.data
        if ev.kind == "grid" and d.get("feed") == "signal" and d.get("iso") == "CAISO":
            seen[(d["location"], d["price_interval_start"])] = d["price_now"]
    if not seen:
        sys.exit("no CAISO grid signals in this timeline")
    ok = True
    for (node, start), logged in seen.items():
        direct = oasis_lmp(node, datetime.fromisoformat(start))
        match = abs(direct - logged) < 1e-3
        ok &= match
        print(f"{node} {start}  timeline ${logged:.5f}  OASIS ${direct:.5f}  {'MATCH' if match else 'DIFFERENT'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/latest/timeline.jsonl")
