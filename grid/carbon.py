"""Carbon intensity of the live fuel mix. Factors (gCO2 per kWh generated) come from
config/isos.yaml with their source; nothing here is typed in."""
from __future__ import annotations


def intensity_gco2_per_kwh(mix_mw: dict[str, float], factors: dict[str, float]) -> tuple[float, dict]:
    """Generation-weighted average of the emission factors.

    Negative entries (batteries charging, solar at night reading slightly below zero) are load,
    not generation, and are excluded. Returns (gCO2/kWh, detail) where detail lists the share
    and factor of every source that contributed, so the dashboard can show its work."""
    gen = {k: float(v) for k, v in mix_mw.items() if k in factors and float(v) > 0}
    total = sum(gen.values())
    if total <= 0:
        raise ValueError("fuel mix has no positive generation")
    detail = {
        k: {"mw": v, "share": v / total, "factor_gco2_per_kwh": factors[k]} for k, v in gen.items()
    }
    g = sum(v * factors[k] for k, v in gen.items()) / total
    return g, detail
