"""The city map's real places (config/cities.yaml, docs/evidence/city/*.json from scripts/fetch_city.py): every hospital
is a named OpenStreetMap place inside its city's box, with the source and licence recorded."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_every_city_has_its_real_hospitals_with_source_and_licence():
    for c in yaml.safe_load((ROOT / "config/cities.yaml").read_text())["cities"]:
        d = json.loads((ROOT / "docs/evidence/city" / f"{c['id']}.json").read_text())
        w, n, e, s = c["viewbox"]
        assert "OpenStreetMap" in d["source"] and "ODbL" in d["license"] and d["fetched_at"]
        assert len(d["hospitals"]) >= 20, c["id"]
        for h in d["hospitals"]:
            assert h["name"] and h["osm"] and w <= h["lon"] <= e and s <= h["lat"] <= n, h
