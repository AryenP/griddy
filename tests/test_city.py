"""The city map's real places (config/cities.yaml, docs/evidence/city/*.json from scripts/fetch_city.py): every hospital
is a named OpenStreetMap place inside its city's box, with the source and licence recorded."""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_every_city_has_its_real_hospitals_with_source_and_licence():
    for c in yaml.safe_load((ROOT / "config/cities.yaml").read_text())["cities"]:
        d = json.loads((ROOT / "docs/evidence/city" / f"{c['id']}.json").read_text())
        w, n, e, s = c["viewbox"]
        assert "OpenStreetMap" in d["source"] and "ODbL" in d["license"] and d["fetched_at"]
        assert len(d["hospitals"]) >= 10, c["id"]                 # San Francisco has 16 places
        for h in d["hospitals"]:
            assert h["name"] and h["osm"] and w <= h["lon"] <= e and s <= h["lat"] <= n, h


def test_the_route_serves_each_city_with_its_source_and_licence():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import make_router
    app = FastAPI()
    app.include_router(make_router(object()))
    got = {c["id"]: c for c in TestClient(app).get("/api/cities").json()}
    assert set(got) == {"san-francisco"} and got["san-francisco"]["iso"] == "CAISO"
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
    assert c.get("/api/cities/san-francisco/map").json()["area"] == "SoMa to Mission Bay"
    assert c.get("/api/cities/san-francisco-datacenters/map").json()["kind"] == "datacenters"
    assert c.get("/api/cities/houston/map").status_code == 404           # Texas left the demo (Sun 03:00)
    assert c.get("/api/cities/..%2F..%2F.env/map").status_code == 404 and c.get("/api/cities/nowhere/map").status_code == 404


def test_a_plant_on_the_grid_view_is_named_only_with_a_source():
    # config/isos.yaml `places`: a fuel gets a real plant's name only where that plant is the whole number (Aryen, Sun
    # 01:10: "make the unnamed stuff into actual locations"); a total of many plants keeps its fuel's name
    import re
    world = (ROOT / "web/world.js").read_text()
    fuels = set(re.findall(r'\[/[^/]+/i, "(\w+)", "\w+"\]', world))          # the plant titles world.js draws
    assert {"Gas", "Nuclear", "Imports"} <= fuels
    isos = yaml.safe_load((ROOT / "config/isos.yaml").read_text())["isos"]
    assert isos["CAISO"]["places"]["Nuclear"]["name"] == "Diablo Canyon"
    for iso, c in isos.items():
        for fuel, p in (c.get("places") or {}).items():
            assert fuel in fuels and p["name"] and p["note"] and p["source"], (iso, fuel)
    assert '"iso_places"' in (ROOT / "api/app.py").read_text() and '"iso_places"' in (ROOT / "HANDOFF.md").read_text()
    assert "d.iso_places" in (ROOT / "web/demo.js").read_text()


@pytest.mark.parametrize("area, at_least", [("san-francisco", 4), ("bay-area", 50)])
def test_every_data_center_is_mapped_with_its_source_and_never_its_operator(area, at_least):
    """scripts/fetch_datacenters.py, the data centers' view (Aryen, Sun 03:00 and 04:00): San Francisco's opens on a
    click, the Bay Area's is kept for later. OpenStreetMap, ODbL; address and outline only, because the operators take
    no part in this demo; each joined to a substation."""
    d = json.loads((ROOT / f"docs/evidence/city/{area}-datacenters-map.json").read_text())
    assert d["kind"] == "datacenters" and "OpenStreetMap" in d["source"] and "ODbL" in d["license"] and d["fetched_at"]
    dcs = d["data_centers"]
    assert d["counts"]["data_centers"] == len(dcs) >= at_least and d["counts"]["in_sf"] >= 4
    assert {"365 Main Street", "360 Spear Street", "200 Paul Avenue"} <= {x["address"] for x in dcs if x["in_sf"]}
    assert not any(k in x for x in dcs for k in ("name", "operator", "brand"))      # never the operator's name
    assert all(abs(x["x"]) <= d["half_m"] and abs(x["z"]) <= d["half_m"] for x in dcs)
    layers = {"substations": "substations", "place names": "places", "power lines": "lines", "shoreline": "coast", "roads": "roads",
              "city names": "places", "transmission lines": "lines", "freeways": "roads"}           # the second three: the Bay's first file
    missing = set(d["missing"])
    assert missing <= set(layers)
    for key in set(layers.values()):                                   # every layer: drawn, or said missing
        assert d[key] or {n for n, k in layers.items() if k == key} & missing, key
    if area == "san-francisco":                                     # what a click opens: every one joined to a named substation
        assert 'const DC_MAP = "san-francisco-datacenters"' in (ROOT / "web/demo.js").read_text()
        assert all(x["substation"] and x["substation"]["name"] and x["substation"]["km"] < 5 for x in dcs)
