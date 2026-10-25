"""Fetch the hospitals of each city in config/cities.yaml from OpenStreetMap (Nominatim search, ODbL) into
docs/evidence/city/<id>.json, once, so the demo needs no network for them. Usage: uv run python scripts/fetch_city.py"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
URL = "https://nominatim.openstreetmap.org/search"
UA = "Griddy-hackathon-demo/1.0"          # Nominatim's policy asks for an identifying agent; one request per second


def main() -> None:
    cities = yaml.safe_load((ROOT / "config/cities.yaml").read_text())["cities"]
    for c in cities:
        w, n, e, s = c["viewbox"]
        r = httpx.get(URL, params={"q": "hospital", "format": "jsonv2", "limit": 40, "bounded": 1,
                                   "viewbox": f"{w},{n},{e},{s}"}, headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
        places = [{"name": p["name"], "lat": float(p["lat"]), "lon": float(p["lon"]), "osm": f"{p['osm_type']}/{p['osm_id']}"}
                  for p in r.json() if p.get("type") == "hospital" and p.get("name")]
        out = {"city": c["name"], "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "source": f"OpenStreetMap via Nominatim search 'hospital' in viewbox {c['viewbox']}",
               "license": "© OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
               "hospitals": places}
        (ROOT / "docs/evidence/city" / f"{c['id']}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(c["id"], len(places), "hospitals")
        time.sleep(1.2)


if __name__ == "__main__":
    main()
