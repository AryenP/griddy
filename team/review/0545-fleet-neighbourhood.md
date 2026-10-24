# K1: deep review of the fleet and the simulated neighbourhood

Reviewer: machine 3 (Krish). Code at main `deda373` (Sat 05:43). Scope per team/3-krish.md K1: `fleet/agent.py`,
`fleet/hub.py`, `neighbourhood/model.py`, their wiring in `controller/execute.py`, `api/app.py`, `api/routes.py`,
DECISIONS 05:10-05:45, HANDOFF.md. `pytest -q` on main: 299 passed, 2 skipped (Windows; `tests/test_meter.py`
excluded, it imports `fcntl`).

Every finding marked **reproduced** comes from `team/review/tools/k1_repro.py`. It drives the real `Neighbourhood`
and `Fleet` classes with the real captured CAISO signal (`tests/fixtures/real_timeline_solve_20261023.jsonl`) and
real powermetrics samples (the idle stretch, seconds 17-40, of `tests/fixtures/real_timeline_calibrate_20261023.jsonl`:
23 samples, mean 1.23 W, range 0.18-3.79 W). Re-run: `python team/review/tools/k1_repro.py .` from the repo root.

Most severe first. Each needs an issue (or a "not a bug" line); issues are pending until `gh` works on machine 3.

## 1. HIGH: a laptop that is plugged in, or drops off Wi-Fi, counts as a reduction (reproduced)
`fleet/hub.py:59-63` returns no watts when the battery reports none (plugged in) or heartbeats stop for
`stale_s` (5 s); `fleet/hub.py:102-106` then drops that laptop from the total the cap is judged on, and
`agent/reporter.py:124` falls back to the Mac's own watts for those seconds. The laptop is still drawing power.
Reproduced: Mac 5.0 W plus a busy laptop on battery 11.4 W = 16.4 W; plug the laptop in, or stop its heartbeats,
and the "measured" total reads 5.0 W. That is an 11.4 W "cut" in the receipts, time to compliance and dashboard
with nothing shed. A judge who unplugs or plugs a laptop during the demo would see it.
Expected: a site that leaves while a cap is in force stays in the total at its last reading (marked stale), or
the window is flagged in the report ("site lap1 left at 05:20:31: its watts are not measured after that");
membership changes during a cap are listed as a caveat in the Report's shortfalls.

## 2. HIGH: the neighbourhood's cut is sized once, so diesel runs even when Brownout fully complies (reproduced)
`neighbourhood/model.py:131-132` calls `_call_for_cut` once per scenario (`self.cap_id is None`), and
`model.py:155-161` sizes the cut for the line at that moment (sim hour 16.44 on the real CAISO forecast: 14.2 %).
The forecast keeps rising to its peak (18:30) while solar falls, and no second call is made. Reproduced: with the
cut fully met from the trigger onward (our sites and the simulated data centers both at 1 - 14.2 %), the line
still peaks at 111 % of its limit, so the diesel runs with Brownout on. The "diesel avoided" figure and the
story ("Brownout keeps the line under its limit") do not hold on today's real forecast shape.
Expected: size the call for the worst loading in the remaining replay (the forecast is known), or re-issue a
deeper cap when loading crosses the trigger again.

## 3. HIGH: with our sites idle, the simulated data centers follow meter noise (reproduced)
`neighbourhood/model.py:104-110` takes our sites' response as their 10-s mean over the pre-cap baseline, and
`model.py:112-113` scales 228 kW of simulated flexible load by it. With the Mac idle (all deferrable work in later
slots, as DECISIONS 05:17 found under live prices), the baseline is ~1 W and the ratio is noise. Reproduced on
the real idle stretch: the ratio ranged 0.72-1.46 across 10-s windows with no knob moved, so the simulated data
centers swung between 315 and 484 kW. The cut the line asks for (14.2 % of a 1.23 W baseline = 1.057 W target)
sits inside the idle noise band (0.18-3.79 W), so compliance and time to compliance are decided by noise too.
Expected: the simulated data centers follow us only when our sites have flexible load running (e.g. a deferrable
job was running at the cap, or the baseline is at least `idle_w + some W`); otherwise they hold and the page says
"our sites had nothing to shed". Before the time-lapse in the demo, make sure training or batch is running.

## 4. MEDIUM: anyone on the network can post a laptop's "measured" watts
`api/routes.py:118-128` (`POST /api/sites/{site_id}/beat` and `/calibration`) accept any body for a site id in
`config/fleet.yaml` (public in the repo) with no token. On the venue network, where judges' phones are invited
by QR code, any device can inject watts into the total the cap is judged on, the receipts and the evidence.
Expected: a shared secret from `.env` (header) checked on both routes; reject otherwise.

## 5. MEDIUM: a multi-day load forecast breaks the homes curve (reproduced)
`neighbourhood/model.py:85-96` reduces every forecast point to its hour of day and bisects that list. ERCOT's
`get_load_forecast("today")` (grid/isos.py:62) returns several days (DECISIONS 23 Oct 21:40: republished hourly),
so the list is not monotonic: the bisect lands on a later day, and the scale uses the maximum over all days.
Reproduced with the real CAISO day plus a differently shaped second day: homes at 16:00 / 18:30 / 20:00 read
684 / 758 / 736 kW from one day, 717 / 605 / 584 kW once a second day is present. Under ERCOT the "evening peak"
would be drawn from the wrong day.
Expected: keep only today's points (in the ISO's time zone) before interpolating.

## 6. MEDIUM: stopping the time-lapse leaves its real cap in force
`neighbourhood/model.py:185-191` (`stop`) does not withdraw the CapEvent it handed to the dispatcher
(`api/app.py:100-107`); `controller/execute.py` has no remove path (`add_event` at :90 only). The cap was issued
for the remaining replay + 30 s (`model.py:168`), so after `POST /api/neighbourhood {"action": "stop"}` the Mac
stays capped for up to two minutes, and `start` again issues a second cap while the first is in force.
Expected: `stop` withdraws its own cap (by `cap_id`) and logs that it did.

## 7. LOW: the simulated call is labelled source "ui"
`neighbourhood/model.py:168` creates `CapEvent(source="ui", ...)`; `CapEvent.source` (core/types.py) has no value
for it. The reason text says "simulated neighbourhood line ..." so it is labelled, but receipts and the operator
page show "from ui". Expected: a `simulated` source, or the reason shown wherever the source is.

## 8. LOW: "no baseline yet" is logged every second of the time-lapse
`neighbourhood/model.py:163-166` returns without setting `cap_id`, so `tick` calls it again each second: up to 90
identical notes in the timeline. Expected: log it once per scenario.

## 9. LOW: outside the time-lapse the line uses the Mac's clock, the forecast uses the ISO's
`neighbourhood/model.py:71` takes the hour from `datetime.fromtimestamp(now)` (the Mac's zone, Pacific); forecast
points carry the ISO's zone. Under ERCOT the idle line is two hours off.

## Not bugs (checked)
- Single Mac, no laptops: `Fleet.combine` returns the reading unchanged (`fleet/hub.py:105-106`), `meter_lag_s()`
  is 0, `idle_drift` and `solve_cal` behave as before; the 299 tests pass. Behaviour unchanged.
- Neighbourhood without the time-lapse: it is enabled by default (`config/neighbourhood.yaml` sets a limit), ticks
  every second and logs `neighbourhood` events (with `simulated: true`) every 10 s into every run, including
  evidence runs. It issues no cap outside the time-lapse, and `agent/reporter.py` ignores the kind, so no simulated
  number reaches a Report or Comparison.
- Laptop meter lag (~1 min, DECISIONS 05:28): documented, and the executor waits `meter_lag_s` before judging.
- Labelling on pages: no page renders the neighbourhood yet (`web/` has no reference to it); re-check when the
  page lands (machine 2) that every value except `ours_w` says "simulated".
