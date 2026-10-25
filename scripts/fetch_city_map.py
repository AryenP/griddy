"""Fetch one real square of each city in config/cities.yaml (its `map` block) from the OpenStreetMap API, once, into
docs/evidence/city/<id>-map.json: building footprints and heights, streets, parks and water, power lines, substations
and plants, and the hospitals' own outlines. The 3D city view draws these 1:1 (Aryen, Sat: "make this 1 to 1, pull
data from maps online ... just part of it is fine").

Coordinates become metres from the square's centre: x east, z south. A building's height is its OSM `height`, else
`building:levels` x 3.5 m, else an estimate from its type; the file counts which is which so the page can say so.
Usage: uv run python scripts/fetch_city_map.py [city-id ...]   (one request per city; OSM asks for light use)
"""
from __future__ import annotations

import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openstreetmap.org/api/0.6/map"
UA = "Griddy-hackathon-demo/1.0"
ROADS = {"motorway": 5, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 3, "residential": 2, "unclassified": 2,
         "living_street": 2, "service": 1, "motorway_link": 3, "trunk_link": 3, "primary_link": 3, "secondary_link": 2,
         "tertiary_link": 2}
TYPE_HEIGHT = {"hospital": 30.0, "house": 6.0, "detached": 6.0, "residential": 9.0, "apartments": 15.0,
               "commercial": 12.0, "office": 20.0, "retail": 6.0, "garage": 3.0, "parking": 12.0, "industrial": 10.0,
               "university": 15.0, "school": 9.0, "church": 12.0, "roof": 4.0}


def _num(v: str | None) -> float | None:
    m = re.match(r"\s*([\d.]+)", v or "")
    return float(m.group(1)) if m else None


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker in metres."""
    if len(pts) < 4:
        return pts
    (x0, z0), (x1, z1) = pts[0], pts[-1]
    dx, dz = x1 - x0, z1 - z0
    n = math.hypot(dx, dz) or 1e-9
    i, d = max(((k, abs(dz * (x - x0) - dx * (z - z0)) / n) for k, (x, z) in enumerate(pts[1:-1], 1)), key=lambda t: t[1])
    if d <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[: i + 1], tol)[:-1] + _simplify(pts[i:], tol)


def fetch(city: dict) -> dict:
    m = city["map"]
    lat0, lon0, half = m["center"][0], m["center"][1], float(m["half_m"])
    kx, kz = 111320.0 * math.cos(math.radians(lat0)), 110540.0
    dlon, dlat = half / kx, half / kz
    bbox = f"{lon0 - dlon:.5f},{lat0 - dlat:.5f},{lon0 + dlon:.5f},{lat0 + dlat:.5f}"
    r = httpx.get(API, params={"bbox": bbox}, headers={"User-Agent": UA}, timeout=90)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    xy = {n.get("id"): ((float(n.get("lon")) - lon0) * kx, -(float(n.get("lat")) - lat0) * kz) for n in root.iter("node")}
    tags = lambda e: {t.get("k"): t.get("v") for t in e.findall("tag")}                                   # noqa: E731
    ways = {w.get("id"): w for w in root.iter("way")}
    pts_of = lambda w: [xy[nd.get("ref")] for nd in w.findall("nd") if nd.get("ref") in xy]              # noqa: E731
    inside = lambda pts: any(abs(x) <= half and abs(z) <= half for x, z in pts)                          # noqa: E731
    r1 = lambda pts: [[round(x, 1), round(z, 1)] for x, z in pts]                                         # noqa: E731

    out = {"buildings": [], "roads": [], "parks": [], "water": [], "power_lines": [], "power_sites": [], "hospitals": []}
    heights = {"tagged": 0, "levels": 0, "estimated": 0}

    def building(pts, t):
        if len(pts) < 4 or not inside(pts):
            return
        h, how = _num(t.get("height")), "tagged"
        if h is None and _num(t.get("building:levels")) is not None:
            h, how = _num(t["building:levels"]) * 3.5, "levels"
        if h is None:
            h, how = TYPE_HEIGHT.get(t.get("building", ""), 10.0), "estimated"
        heights[how] += 1
        h0 = _num(t.get("min_height")) or 0.0
        hosp = t.get("amenity") == "hospital" or t.get("healthcare") == "hospital" or t.get("building") == "hospital"
        out["buildings"].append({"p": r1(_simplify(pts[:-1] if pts[0] == pts[-1] else pts, 0.8)), "h": round(h, 1),
                                 "h0": round(h0, 1), **({"hospital": True} if hosp else {}),
                                 **({"name": t["name"]} if hosp and t.get("name") else {})})

    for w in ways.values():
        t, pts = tags(w), pts_of(w)
        if len(pts) < 2:
            continue
        if "building" in t or "building:part" in t:
            building(pts, t)
        elif t.get("highway") in ROADS and inside(pts):
            out["roads"].append({"w": ROADS[t["highway"]], "p": r1(_simplify(pts, 1.0)), **({"name": t["name"]} if t.get("name") else {})})
        elif (t.get("leisure") in ("park", "garden") or t.get("landuse") in ("grass", "recreation_ground")) and inside(pts):
            out["parks"].append(r1(_simplify(pts, 2.0)))
        elif (t.get("natural") == "water" or t.get("waterway") in ("riverbank", "canal")) and inside(pts):
            out["water"].append(r1(_simplify(pts, 2.0)))
        elif t.get("power") in ("line", "minor_line", "cable") and inside(pts):
            out["power_lines"].append({"kind": t["power"], "p": r1(pts), **({"voltage": t["voltage"]} if t.get("voltage") else {})})
        elif t.get("power") in ("substation", "plant", "generator") and inside(pts):
            cx, cz = sum(x for x, _ in pts) / len(pts), sum(z for _, z in pts) / len(pts)
            out["power_sites"].append({"kind": t["power"], "x": round(cx, 1), "z": round(cz, 1), **({"name": t["name"]} if t.get("name") else {})})
        if (t.get("amenity") == "hospital" or t.get("healthcare") == "hospital") and t.get("name") and inside(pts):
            cx, cz = sum(x for x, _ in pts) / len(pts), sum(z for _, z in pts) / len(pts)
            out["hospitals"].append({"name": t["name"], "x": round(cx, 1), "z": round(cz, 1), "outline": r1(_simplify(pts, 2.0))})
    for rel in root.iter("relation"):                     # multipolygon buildings: their outer rings
        t = tags(rel)
        if t.get("type") == "multipolygon" and ("building" in t or "building:part" in t):
            for mem in rel.findall("member"):
                if mem.get("type") == "way" and mem.get("role") == "outer" and mem.get("ref") in ways:
                    building(pts_of(ways[mem.get("ref")]), {**tags(ways[mem.get("ref")]), **t})
        if (t.get("amenity") == "hospital" or t.get("healthcare") == "hospital") and t.get("name"):
            outer = [pts_of(ways[m.get("ref")]) for m in rel.findall("member") if m.get("type") == "way" and m.get("ref") in ways]
            pts = [p for ring in outer for p in ring]
            if pts and inside(pts):
                cx, cz = sum(x for x, _ in pts) / len(pts), sum(z for _, z in pts) / len(pts)
                out["hospitals"].append({"name": t["name"], "x": round(cx, 1), "z": round(cz, 1), "outline": []})
    for n in root.iter("node"):
        t = tags(n)
        if t.get("power") in ("substation", "plant") and n.get("id") in xy and inside([xy[n.get("id")]]):
            x, z = xy[n.get("id")]
            out["power_sites"].append({"kind": t["power"], "x": round(x, 1), "z": round(z, 1), **({"name": t["name"]} if t.get("name") else {})})
    out["buildings"].sort(key=lambda b: -b["h"])
    return {"city": city["name"], "area": m["name"], "center": [lat0, lon0], "half_m": half, "bbox": bbox,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": f"OpenStreetMap API v0.6 map call, bbox {bbox}",
            "license": "© OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
            "heights": heights, **out}


def main(ids: list[str]) -> None:
    for c in yaml.safe_load((ROOT / "config/cities.yaml").read_text())["cities"]:
        if ids and c["id"] not in ids:
            continue
        d = fetch(c)
        path = ROOT / "docs/evidence/city" / f"{c['id']}-map.json"
        path.write_text(json.dumps(d, separators=(",", ":")) + "\n")
        print(c["id"], {k: len(v) for k, v in d.items() if isinstance(v, list)}, d["heights"], f"{path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1:])
