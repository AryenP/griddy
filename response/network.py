"""One square of a real city as a network Griddy can switch (config/networks.yaml).

The square, its buildings, the substation, the plants, the 138 kV lines, the hospitals and the streets are real
OpenStreetMap data (docs/evidence/city/<id>-map.json). The feeders are simulated: the square is cut into the same 4 x 4
zones web/world.js draws, one feeder per row; each zone's share of the load is its buildings' real floor volume.
Crews drive the real streets: the shortest path on the OSM road graph from their (simulated) depot to the site.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

ZONES = 4                       # 4 x 4 zones, as web/world.js draws them
SNAP_M = 12.0                   # roads whose vertices pass this close are joined (the map's lines are simplified)
CORNERS = {"ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1)}   # x east, z south


def zone_of(x: float, z: float, half: float) -> int:
    col = min(ZONES - 1, max(0, int((x + half) / (2 * half) * ZONES)))
    row = min(ZONES - 1, max(0, int((z + half) / (2 * half) * ZONES)))
    return col + ZONES * row


def _area(pts: list) -> float:
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))) / 2


class Roads:
    """The OSM streets as a graph: shortest paths in metres."""

    def __init__(self, roads: list[dict]):
        pts, edges = [], []
        for r in roads:
            base = len(pts)
            pts.extend(tuple(p) for p in r["p"])
            edges.extend((base + i, base + i + 1) for i in range(len(r["p"]) - 1))
        self.xy = np.array(pts, dtype=float)
        self.adj: list[list[tuple[int, float]]] = [[] for _ in pts]
        for a, b in edges:
            self._join(a, b)
        # simplified OSM ways can cross without sharing a vertex: join every vertex to the ends of any segment of
        # another road it passes within SNAP_M of
        seg_a = np.array([a for a, _ in edges]); seg_b = np.array([b for _, b in edges])
        A, B = self.xy[seg_a], self.xy[seg_b]
        AB = B - A
        L2 = np.maximum((AB ** 2).sum(1), 1e-9)
        for i in range(len(pts)):
            P = self.xy[i]
            t = np.clip(((P - A) * AB).sum(1) / L2, 0, 1)
            d = np.hypot(*(A + AB * t[:, None] - P).T)
            for k in np.nonzero(d < SNAP_M)[0]:
                a, b = int(seg_a[k]), int(seg_b[k])
                if i not in (a, b):
                    self._join(i, a); self._join(i, b)

    def _join(self, a: int, b: int) -> None:
        w = float(math.dist(self.xy[a], self.xy[b]))
        self.adj[a].append((b, w)); self.adj[b].append((a, w))

    def nearest(self, x: float, z: float) -> int:
        return int(np.argmin(np.hypot(self.xy[:, 0] - x, self.xy[:, 1] - z)))

    def route(self, start: tuple[float, float], goal: tuple[float, float]) -> tuple[float, list[list[float]]] | None:
        """Shortest drive from the road nearest `start` to the road nearest `goal`: (metres, points)."""
        s, g = self.nearest(*start), self.nearest(*goal)
        dist, prev, seen = {s: 0.0}, {}, set()
        q = [(0.0, s)]
        while q:
            d, u = heapq.heappop(q)
            if u in seen:
                continue
            if u == g:
                break
            seen.add(u)
            for v, w in self.adj[u]:
                if d + w < dist.get(v, math.inf):
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(q, (d + w, v))
        if g not in dist:
            return None
        path, u = [g], g
        while u != s:
            u = prev[u]; path.append(u)
        pts = [[round(float(self.xy[i][0]), 1), round(float(self.xy[i][1]), 1)] for i in reversed(path)]
        return dist[g], pts


class Network:
    """Zones with their real share of load and their hospitals; the real substation, plants and lines; crew routes."""

    def __init__(self, city_id: str, m: dict, cfg: dict):
        self.city_id, self.cfg, self.half = city_id, cfg, float(m["half_m"])
        vol = [0.0] * ZONES * ZONES                           # each zone's floor volume, hospitals apart
        crit = [0.0] * ZONES * ZONES
        for b in m["buildings"]:
            cx = sum(p[0] for p in b["p"]) / len(b["p"]); cz = sum(p[1] for p in b["p"]) / len(b["p"])
            z = zone_of(cx, cz, self.half)
            v = _area(b["p"]) * max(3.0, b["h"] - b.get("h0", 0))
            (crit if b.get("hospital") else vol)[z] += v
        total = (sum(vol) + sum(crit)) or 1.0
        self.load = [v / total for v in vol]                  # each zone's share of the square's load, hospitals apart
        self.critical_load = sum(crit) / total                # the hospitals' share: islanded on the plants, never shed
        sites = {s.get("name"): s for s in m.get("power_sites", []) if s.get("name")}
        if cfg["substation"] not in sites:
            raise KeyError(f"{cfg['substation']!r} is not in {city_id}'s map")
        self.substation = sites[cfg["substation"]]
        self.backup = [sites[n] for n in cfg.get("backup", []) if n in sites]
        sx, sz = self.substation["x"], self.substation["z"]
        near = lambda p: math.dist(p, (sx, sz)) < 260           # noqa: E731  (one line ends at a junction 240 m off)
        self.lines = [l for l in m.get("power_lines", []) if l["kind"] == "line" and l.get("voltage") == "138000"
                      and (near(l["p"][0]) or near(l["p"][-1])) and math.dist(l["p"][0], l["p"][-1]) > 300]
        self.lines.sort(key=lambda l: -math.dist(l["p"][0], l["p"][-1]))
        self.roads = Roads(m["roads"])
        self.hospitals = [h["name"] for h in m.get("hospitals", [])
                          if abs(h["x"]) <= self.half and abs(h["z"]) <= self.half]

    def line_name(self, i: int) -> str:
        """Where a 138 kV line into the substation comes from, by the far end's direction."""
        l = self.lines[i]
        far = max((l["p"][0], l["p"][-1]), key=lambda p: math.dist(p, (self.substation["x"], self.substation["z"])))
        ang = math.degrees(math.atan2(-(far[1] - self.substation["z"]), far[0] - self.substation["x"])) % 360
        compass = ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"][int((ang + 22.5) // 45) % 8]
        return f"the 138 kV line from the {compass}"

    def depot(self, corner: str) -> tuple[float, float]:
        sx, sz = CORNERS[corner]
        i = self.roads.nearest(sx * self.half * 0.92, sz * self.half * 0.92)
        return float(self.roads.xy[i][0]), float(self.roads.xy[i][1])

    def site_of(self, kind: str, line: int = 0) -> tuple[float, float]:
        if kind == "line" and self.lines:
            l = self.lines[line]
            inside = [p for p in l["p"] if abs(p[0]) <= self.half and abs(p[1]) <= self.half]
            p = inside[len(inside) // 2] if inside else l["p"][-1]
            return float(p[0]), float(p[1])
        return float(self.substation["x"]), float(self.substation["z"])
