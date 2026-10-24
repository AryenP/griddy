"""At grid scale: what this Mac's measured cut would mean on ERCOT. An ESTIMATE from public data, and labelled so.

Inputs (config/site.yaml `scale`): ERCOT's live actual system demand (gridstatus, keyless), the large loads ERCOT
observes running (its monthly operational overview), the large-load queue (cited), and this Mac's measured cut
under the same utility call (evidence of record). Output: the megawatts those running large loads would free if
they cut the same share, and that as a share of ERCOT's demand right now."""
from __future__ import annotations


def estimate(cfg: dict, demand_mw: float | None, demand_t: str | None) -> dict:
    running = float(cfg["large_loads_running_mw"])
    cut = float(cfg["our_cut_pct"])
    freed = running * cut / 100
    return {"estimate": True, "iso": "ERCOT", "demand_mw": demand_mw, "demand_t": demand_t,
            "large_loads_running_mw": running, "large_loads_approved_mw": float(cfg["large_loads_approved_mw"]),
            "large_loads_source": cfg["large_loads_source"], "large_loads_url": cfg["large_loads_url"],
            "queue_gw": float(cfg["queue_gw"]), "queue_source": cfg["queue_source"], "queue_url": cfg["queue_url"],
            "our_cut_pct": cut, "our_cut_source": cfg["our_cut_source"], "freed_mw": freed,
            "share_of_demand_pct": 100 * freed / demand_mw if demand_mw else None}
