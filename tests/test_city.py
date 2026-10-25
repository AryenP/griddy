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
        assert len(d["hospitals"]) >= 10, c["id"]                 # San Francisco has 16 places; Houston more
        for h in d["hospitals"]:
            assert h["name"] and h["osm"] and w <= h["lon"] <= e and s <= h["lat"] <= n, h


def test_the_route_serves_each_city_with_its_source_and_licence():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import make_router
    app = FastAPI()
    app.include_router(make_router(object()))
    got = {c["id"]: c for c in TestClient(app).get("/api/cities").json()}
    assert set(got) == {"houston", "san-francisco"} and got["houston"]["iso"] == "ERCOT" and got["san-francisco"]["iso"] == "CAISO"
    assert all("ODbL" in c["license"] and c["hospitals"] for c in got.values())


def test_each_city_has_a_real_square_drawn_one_to_one():
    """scripts/fetch_city_map.py: OpenStreetMap buildings with heights, streets and hospitals, in metres from the centre."""
    for c in yaml.safe_load((ROOT / "config/cities.yaml").read_text())["cities"]:
        d = json.loads((ROOT / "docs/evidence/city" / f"{c['id']}-map.json").read_text())
        half = c["map"]["half_m"]
        assert "OpenStreetMap" in d["source"] and "ODbL" in d["license"] and d["half_m"] == half
        assert len(d["buildings"]) >= 100 and len(d["roads"]) >= 100 and d["hospitals"], c["id"]
        assert sum(d["heights"].values()) == len(d["buildings"]) and d["heights"]["tagged"] > 0
        assert all(b["h"] > 0 and len(b["p"]) >= 3 for b in d["buildings"])
        assert any(abs(x) <= half and abs(z) <= half for b in d["buildings"] for x, z in b["p"])


def test_the_map_route_serves_only_named_cities():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import make_router
    app = FastAPI()
    app.include_router(make_router(object()))
    c = TestClient(app)
    assert c.get("/api/cities/houston/map").json()["area"] == "Texas Medical Center"
    assert c.get("/api/cities/..%2F..%2F.env/map").status_code == 404 and c.get("/api/cities/nowhere/map").status_code == 404
