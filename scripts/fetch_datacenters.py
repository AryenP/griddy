"""Fetch every data center OpenStreetMap maps in an area, once, into docs/evidence/city/<area>-datacenters-map.json
(Aryen, Sun 03:00: "data center needs to expand when clicked"; 04:00: "the datacenters connected to sf, not all of
america"; "dont get rid of ur progress"). The Grid view opens San Francisco's when the data center is clicked; the
Bay Area's is kept for later.

What is kept, all real and mapped (OpenStreetMap, ODbL):
  - data centers (telecom=data_center or building=data_center): address and outline only, never the operator's name
    (the operators take no part in this demo); footprint area from the outline; the nearest substation (in San
    Francisco: any, a named PG&E one first; around the Bay: 115 kV or more) and its distance, as the crow flies, because
    no public source gives a data center's feeder;
  - the base map: substations, power lines, the shoreline, main roads and place names.
Coordinates become metres from the box's centre: x east, z south (as in scripts/fetch_city_map.py).
Usage: uv run python scripts/fetch_datacenters.py [--area sf|bay] [--cached]   (OSM asks for light use)
  --cached writes the file from the queries already fetched, with no network: the backdrop layers the server has not
  given yet are listed in `missing` and the page draws without them; a later run fills them in.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
UA = "Griddy-hackathon-demo/1.0"
MIRRORS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
SF = (37.7080, -122.5150, 37.8120, -122.3570)         # the city of San Francisco (south, west, north, east)
# Each area: its box (south, west, north, east), name, and the layers' queries with their tiling (the Bay's are big).
AREAS = {
    "sf": {"box": (37.700, -122.520, 37.835, -122.350), "name": "San Francisco", "min_kv": 0,
           "subs": ('nwr["power"="substation"];out center;', 1),
           "places": ('node["place"~"^(neighbourhood|suburb)$"]["name"];out;', 1),
           "lines": ('way["power"~"^(line|cable)$"]["voltage"];out tags geom;', 1),
           "coast": ('way["natural"="coastline"];out geom;', 1),
           "roads": ('way["highway"~"^(motorway|trunk|primary)$"];out geom;', 1), "tol": 6.0},
    "bay": {"box": (37.20, -122.62, 38.05, -121.70), "name": "San Francisco Bay Area", "min_kv": 115,
            "subs": ('nwr["power"="substation"]["voltage"~"(115000|230000|500000)"];out center;', 2),
            "places": ('node["place"~"^(city|town)$"]["name"];out;', 1),
            "lines": ('way["power"="line"]["voltage"~"(230000|500000)"];out tags geom;', 2),
            "coast": ('way["natural"="coastline"];out geom;', 4),
            "roads": ('way["highway"="motorway"];out geom;', 3), "tol": 60.0},
}
KEY = sys.argv[sys.argv.index("--area") + 1] if "--area" in sys.argv else "sf"
AREA = AREAS[KEY]
OUT = ROOT / "docs/evidence/city" / ("bay-area-datacenters-map.json" if KEY == "bay" else f"san-francisco-datacenters-map.json")
S, W, N, E = AREA["box"]
LAT0, LON0 = (S + N) / 2, (W + E) / 2
M_LAT = 111_320.0
M_LON = M_LAT * math.cos(math.radians(LAT0))


def xz(lat: float, lon: float) -> list[float]:
    return [round((lon - LON0) * M_LON, 1), round((LAT0 - lat) * M_LAT, 1)]


CACHE = Path(tempfile.gettempdir()) / "griddy-overpass"   # each finished query, so a rerun picks up where it stopped


def overpass(q: str, tiles: int = 1) -> list[dict]:
    """One query over the box, in `tiles` x `tiles` pieces for the heavy layers (shoreline, freeways)."""
    out, seen = [], set()
    for i in range(tiles):
        for j in range(tiles):
            s, n = S + (N - S) * i / tiles, S + (N - S) * (i + 1) / tiles
            w, e = W + (E - W) * j / tiles, W + (E - W) * (j + 1) / tiles
            for el in _query(f"[out:json][timeout:110][bbox:{s},{w},{n},{e}];{q}"):
                if (el["type"], el["id"]) not in seen:
                    seen.add((el["type"], el["id"]))
                    out.append(el)
    return out


CACHED_ONLY = "--cached" in sys.argv


def _query(body: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    hit = CACHE / f"{hashlib.sha1(body.encode()).hexdigest()[:16]}.json"
    if hit.is_file():
        return json.loads(hit.read_text())
    if CACHED_ONLY:
        raise RuntimeError("not fetched yet")
    last: Exception | None = None
    for url in MIRRORS:                              # the main server first: when full it says so at once (502)
        for attempt in range(6 if url == MIRRORS[0] else 1):
            try:
                r = httpx.post(url, data={"data": body}, headers={"User-Agent": UA}, timeout=130)
                if r.status_code in (429, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"busy: {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                els = r.json()["elements"]
                hit.write_text(json.dumps(els))
                return els
            except Exception as e:
                last = e
                time.sleep(8)
    raise RuntimeError(f"every Overpass mirror failed: {last!r}")


def simplify(pts: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas-Peucker in metres: enough to draw at the scale of the Bay. A closed ring (a building, an island) is split
    at its farthest point first: its two ends are the same point, which would collapse it."""
    if len(pts) > 3 and pts[0] == pts[-1]:
        ring = pts[:-1]
        far = max(range(len(ring)), key=lambda k: (ring[k][0] - ring[0][0]) ** 2 + (ring[k][1] - ring[0][1]) ** 2)
        return _dp(ring[: far + 1], tol)[:-1] + _dp(ring[far:] + [ring[0]], tol)
    return _dp(pts, tol)


def _dp(pts: list[list[float]], tol: float) -> list[list[float]]:
    if len(pts) < 3:
        return pts
    (x0, z0), (x1, z1) = pts[0], pts[-1]
    dx, dz = x1 - x0, z1 - z0
    L = math.hypot(dx, dz) or 1.0
    i, dmax = 0, -1.0
    for k in range(1, len(pts) - 1):
        d = abs(dz * (pts[k][0] - x0) - dx * (pts[k][1] - z0)) / L
        if d > dmax:
            i, dmax = k, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return _dp(pts[: i + 1], tol)[:-1] + _dp(pts[i:], tol)


def geom(el: dict) -> list[list[float]]:
    if el["type"] == "way":
        return [xz(g["lat"], g["lon"]) for g in el.get("geometry", [])]
    if el["type"] == "relation":                     # a multipolygon: its largest outer ring
        rings = [[xz(g["lat"], g["lon"]) for g in m.get("geometry", [])] for m in el.get("members", []) if m.get("role") == "outer"]
        return max(rings, key=len) if rings else []
    return []


def center(el: dict) -> tuple[float | None, float | None]:
    """A node's own point; a way's or relation's middle, from its geometry (or its bounds)."""
    if el["type"] == "node":
        return el.get("lat"), el.get("lon")
    g = el.get("geometry") or [q for m in el.get("members", []) if m.get("role") == "outer" for q in m.get("geometry", [])]
    if g:
        return sum(q["lat"] for q in g) / len(g), sum(q["lon"] for q in g) / len(g)
    b = el.get("bounds")
    return ((b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2) if b else (None, None)


def footprint(pts: list[list[float]]) -> float:
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))) / 2


def kv(tag: str | None) -> float:
    try:
        return max(float(v) for v in str(tag).split(";")) / 1000
    except ValueError:
        return 0.0


def main() -> None:
    dcs = overpass('(nwr["telecom"="data_center"];nwr["building"="data_center"];);out tags geom;')   # the point: required
    missing = []
    def optional(name: str, q: str, tiles: int = 1) -> list[dict]:   # the backdrop: drawn when the server can give it
        try:
            return overpass(q, tiles=tiles)
        except RuntimeError:
            missing.append(name)
            return []
    subs = optional("substations", *AREA["subs"])
    places = [p for p in optional("place names", *AREA["places"]) if "lat" in p]
    lines = optional("power lines", *AREA["lines"])
    coast = optional("shoreline", *AREA["coast"])
    roads = optional("roads", *AREA["roads"])

    hv = []
    for s in subs:
        c = s.get("center") or {"lat": s.get("lat"), "lon": s.get("lon")}
        t = s.get("tags", {})
        v = kv(t.get("voltage"))
        if c.get("lat") is not None and v >= AREA["min_kv"]:
            hv.append({"name": t.get("name"), "operator": t.get("operator"), "kv": v, "x": xz(c["lat"], c["lon"])[0], "z": xz(c["lat"], c["lon"])[1]})
    utility = [s for s in hv if s["name"] and "Pacific Gas" in (s["operator"] or "")] or [s for s in hv if s["name"]] or hv

    town = [{"name": p["tags"]["name"], "x": xz(p["lat"], p["lon"])[0], "z": xz(p["lat"], p["lon"])[1],
             "pop": int(p["tags"]["population"]) if str(p["tags"].get("population", "")).isdigit() else None,
             "city": p["tags"].get("place") == "city"} for p in places]

    seen, out = set(), []
    for el in dcs:
        lat, lon = center(el)
        if lat is None:
            continue
        x, z = xz(lat, lon)
        key = (round(x / 40), round(z / 40))         # a node inside its own building's outline: one data center
        if key in seen:
            continue
        seen.add(key)
        t = el.get("tags", {})
        ring = simplify(geom(el), 2.0)
        address = " ".join(v for v in (t.get("addr:housenumber"), t.get("addr:street")) if v) or None
        near = min(utility, key=lambda s: math.hypot(s["x"] - x, s["z"] - z)) if utility else None
        nearest_town = min(town, key=lambda p: math.hypot(p["x"] - x, p["z"] - z)) if town else None
        out.append({"x": x, "z": z, "outline": ring if len(ring) > 2 else [],
                    "address": address, "city": t.get("addr:city") or (nearest_town["name"] if nearest_town else None),
                    "city_mapped": bool(t.get("addr:city")),
                    "in_sf": SF[0] <= lat <= SF[2] and SF[1] <= lon <= SF[3],
                    "area_m2": round(footprint(ring)) if len(ring) > 2 else None,
                    "levels": float(t["building:levels"]) if str(t.get("building:levels", "")).replace(".", "", 1).isdigit() else None,
                    "substation": {"name": near["name"], "operator": near["operator"], "kv": near["kv"], "x": near["x"], "z": near["z"],
                                   "km": round(math.hypot(near["x"] - x, near["z"] - z) / 1000, 2)} if near else None,
                    "osm": f"{el['type']}/{el['id']}"})
    out.sort(key=lambda d: (not d["in_sf"], d["city"] or "~", d["address"] or "~"))

    doc = {
        "kind": "datacenters", "area": AREA["name"], "city": "san-francisco",
        "center": [LAT0, LON0], "bbox": [W, N, E, S], "half_m": round(max((E - W) * M_LON, (N - S) * M_LAT) / 2),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "OpenStreetMap contributors, via the Overpass API", "license": "ODbL 1.0 (openstreetmap.org/copyright)",
        "note": "Data centers as mapped in OpenStreetMap (telecom=data_center or building=data_center): what volunteers "
                "have mapped, not a complete census. Address and outline only; operators are not named.",
        "data_centers": out,
        "substations": [s for s in hv if KEY == "sf" or s["kv"] >= 230],
        "lines": [{"kv": kv(w.get("tags", {}).get("voltage")), "p": simplify(geom(w), AREA["tol"])} for w in lines if len(geom(w)) > 1],
        "roads": [{"p": simplify(geom(w), AREA["tol"])} for w in roads if len(geom(w)) > 1],
        "coast": [simplify(geom(w), AREA["tol"] * 0.7) for w in coast if len(geom(w)) > 1],
        "places": [p for p in town if KEY == "sf" or p["city"] or (p["pop"] or 0) >= 50_000],
    }
    doc["missing"] = missing                          # layers the server could not give this time: the page draws without them
    doc["counts"] = {"data_centers": len(out), "in_sf": sum(d["in_sf"] for d in out),
                     "with_address": sum(1 for d in out if d["address"]), "with_outline": sum(1 for d in out if d["outline"])}
    OUT.write_text(json.dumps(doc, separators=(",", ":")))
    print(f"{OUT.relative_to(ROOT)}: {doc['counts']}, {len(doc['roads'])} freeway ways, {len(doc['lines'])} lines, "
          f"{len(doc['coast'])} shoreline ways, {len(doc['places'])} places, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
