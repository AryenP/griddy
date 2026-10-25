"""At grid scale: what this Mac's measured cut would mean on the live grid's data centers. An ESTIMATE, labelled so.

Inputs (config/site.yaml `scale`): the live grid's demand served now (its fuel mix, the total the Grid page shows), a
stated unit of data center load (1 GW: CAISO publishes no running-data-center figure we can cite), and this Mac's
measured cut under the same utility call (evidence of record). Output: the megawatts that unit would free if it cut
the same share, and that as a share of the grid's demand right now."""
from __future__ import annotations


def estimate(cfg: dict, iso: str, demand_mw: float | None, demand_t: str | None) -> dict:
    flexible = float(cfg["flexible_mw"])
    cut = float(cfg["our_cut_pct"])
    freed = flexible * cut / 100
    return {"estimate": True, "iso": iso, "demand_mw": demand_mw, "demand_t": demand_t,
            "flexible_mw": flexible, "flexible_source": cfg["flexible_source"],
            "our_cut_pct": cut, "our_cut_source": cfg["our_cut_source"], "freed_mw": freed,
            "share_of_demand_pct": 100 * freed / demand_mw if demand_mw else None}
