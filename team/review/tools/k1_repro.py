"""K1 review reproductions. Drives the real neighbourhood/model.py and fleet/hub.py classes with the real
captured CAISO signal (tests/fixtures/real_timeline_solve_20261023.jsonl) and real powermetrics samples
(tests/fixtures/real_timeline_calibrate_20261023.jsonl). Review tooling only; kept with the review so anyone can re-run it: python team/review/tools/k1_repro.py .."""
import json
import statistics
import sys
from datetime import timedelta
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO))

from core.types import GridSignal, PowerReading  # noqa: E402
from fleet.hub import Fleet  # noqa: E402
from neighbourhood.model import Neighbourhood  # noqa: E402
import yaml  # noqa: E402


class Tl:
    def __init__(self):
        self.events = []

    def log(self, kind, **d):
        self.events.append((kind, d))


def grid():
    for line in (REPO / "tests/fixtures/real_timeline_solve_20261023.jsonl").open():
        e = json.loads(line)
        if e["kind"] == "grid":
            return GridSignal.model_validate({k: v for k, v in e["data"].items() if k != "feed"})


def calib_power():
    out = []
    for line in (REPO / "tests/fixtures/real_timeline_calibrate_20261023.jsonl").open():
        e = json.loads(line)
        if e["kind"] == "power":
            out.append((e["data"]["t"], e["data"]["combined_w"]))
    return out


class Ex:
    """Stands in for the executor: the two attributes the model reads, fed with real samples."""
    def __init__(self, sig, power):
        self.signal, self.power = sig, power
        self.base = None

    def baseline_w(self):
        return self.base


cfg = yaml.safe_load((REPO / "config/neighbourhood.yaml").read_text())
sig = grid()
real = calib_power()
t0 = real[0][0]
# The idle stretch of the real capture: seconds 17-40 (all jobs paused; see the fixture's notes).
idle = [(t, w) for t, w in real if 17 <= t - t0 <= 40]
idle_w = [w for _, w in idle]
print(f"real idle samples: n={len(idle_w)} mean={statistics.fmean(idle_w):.2f} W "
      f"min={min(idle_w):.2f} max={max(idle_w):.2f}")

# --- A: response ratio when our sites are idle --------------------------------------------------------
ex = Ex(sig, [])
nb = Neighbourhood(Tl(), ex, cfg)
nb.cap_baseline_w = statistics.fmean(idle_w)     # the pre-cap baseline: mean of the whole idle stretch
rs = []
for i in range(10, len(idle)):
    ex.power = idle[: i + 1]
    r, mean = nb.response(idle[i][0])
    rs.append((r, nb.dc_kw(r)))
dk = [d for _, d in rs]
print(f"A idle Mac: response r from {min(r for r, _ in rs):.2f} to {max(r for r, _ in rs):.2f}; "
      f"simulated data-center load swings {min(dk):.0f}-{max(dk):.0f} kW "
      f"(flexible total {sum(nb.dc_sizes) * nb.flex:.0f} kW) with no knob moved")

# --- B: the cut the line asks for, applied to an idle Mac's baseline ---------------------------------
ex = Ex(sig, idle)
ex.base = statistics.fmean(idle_w)
tl = Tl()
nb = Neighbourhood(tl, ex, cfg)
start = idle[-1][0]
nb.start(start)
fired = None
for s in range(0, 95):
    nb.tick(start + s)
    if nb.pending_cap and fired is None:
        fired = (s, nb.pending_cap)
if fired:
    s, ev = fired
    print(f"B cap fires at +{s} s (sim hour {nb.history[s]['sim_hour']:.2f}): {ev.target_pct}% of an idle "
          f"baseline {ex.base:.2f} W -> target {ex.base * (1 - ev.target_pct / 100):.3f} W, inside the "
          f"idle range {min(idle_w):.2f}-{max(idle_w):.2f} W; duration {ev.duration_s} s, source={ev.source!r}")
    # Full compliance: our sites and the simulated data centers cut exactly the asked share from then on.
    r_full = 1 - ev.target_pct / 100
    worst = max(((h["homes_kw"] or 0) + nb.dc_kw(r_full) - h["solar_kw"]) / nb.limit * 100
                for h in list(nb.history)[s:] if h["scenario"])
    print(f"   with the cut fully met from +{s} s, the line still peaks at {worst:.0f} % of its limit "
          f"(the cut is sized once, at the trigger, and never revised)")
else:
    print("B no cap fired in the scenario")
print(f"   max loading {max(h['loading_pct'] for h in nb.history):.0f} % (no measured samples during this "
      f"replay, so the on/off diesel figures match: {nb.diesel_kwh:.1f}/{nb.diesel_off_kwh:.1f} kWh)")

# --- C: the forecast as ERCOT delivers it (several days): hour-of-day lookup ------------------------
day1 = sorted(sig.load_forecast)
two_day = day1 + [(t + timedelta(days=1), day1[-1 - i][1]) for i, (t, _) in enumerate(day1)]   # day 2: day 1 reversed
sig2 = sig.model_copy(update={"load_forecast": two_day})
one = Neighbourhood(Tl(), Ex(sig, []), cfg)
two = Neighbourhood(Tl(), Ex(sig2, []), cfg)
for h in (16.0, 18.5, 20.0):
    print(f"C hour {h}: homes {one.homes_kw(h, sig):.0f} kW from one day of forecast; "
          f"{two.homes_kw(h, sig2):.0f} kW when the forecast holds a second day (the lookup lands on the later day)")

# --- D: a laptop that drops out or is plugged in during a cap ----------------------------------------
fl = Fleet(Tl(), {"sites": [{"id": "lap1"}], "stale_s": 5, "meter_lag_s": 75}, cal_path=Path("NUL"))
fl.cal = {"lap1": {"idle_w": 8.3, "delta_w": 3.0, "rate_mb_s": 1.0}}
mac = 5.0
totals = []
for s in range(0, 30):
    if s < 10:
        fl.beat("lap1", {"watts": 11.4}, now=1000 + s)            # on battery, busy
    elif s < 20:
        fl.beat("lap1", {"watts": None, "plugged": True}, now=1000 + s)   # plugged in: still drawing
    # s >= 20: no heartbeats (Wi-Fi dropped)
    totals.append(fl.combine(PowerReading(t=1000 + s, combined_w=mac)).combined_w)
print(f"D measured total: on battery {totals[5]:.1f} W; plugged in {totals[15]:.1f} W; "
      f"after its Wi-Fi drops {totals[29]:.1f} W (the laptop still draws ~11 W in both cases)")
