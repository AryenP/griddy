# K14: a judge with only the repo (fresh clone, Krish's Surface Pro 11, Windows 11 ARM64)

Machine 3 (Krish), Sat 20:20-20:35 PT, `git clone https://github.com/AryenP/abc.git` into a new folder at main
`657217f`. No Mac, no .env, no keys. Times are wall-clock.

## Steps
| Step | Command | Time | Result |
|---|---|---|---|
| 1 | `git clone` | 6 s | ok |
| 2 | `uv sync --extra dev` | 9 s (+ installing uv) | **`uv` is not on a fresh Windows machine** and the README never says to install it; I used `pip install uv`, then `python -m uv sync --extra dev`. Worked. |
| 3 | `make verify` | - | **`make` does not exist on Windows.** `uv run python scripts/verify.py` (from team/3-krish.md, not the README): **74 of 74 checks pass, from 10 raw timelines**, 2 s. The strongest thing in the repo for a judge. |
| 4 | `uv run pytest -q` | 9 s | **Runs zero tests**: collection stops at `tests/test_meter.py` (`import fcntl`, Unix only) with "1 error ... Interrupted". With `--ignore tests/test_meter.py`: 483 passed, 3 skipped, 2 failed, 48 s; both failures are the same import through `meter/powermetrics.py:11` (`test_app_pages.py::test_pages_are_always_revalidated`, `test_controller.py::test_scripted_chat_waits_after_each_reply`). |
| 5 | `uv run python -m evals` | 2 s | 121 cases offline: 100 pass, 0 fail, 21 need an LLM (no key). Injection 16/16. |
| 6 | Read README.md only | 10 min | answers below |

## What I could say after ten minutes with the README alone
- **What it does:** schedules AI jobs on one machine against the live grid (prices, fuel mix, alerts) over the next
  24 h, holds a utility's power cap, asks job owners before a deadline slips, and proves it with the machine's measured
  watts; a judge can replay three real grid emergencies through it.
- **How it decides:** a CP-SAT solver over 15-minute slots decides; the LLM only reads requests, negotiates and
  explains; owners and the operator approve; the controller is the only path to a knob. Clear.
- **Measured vs simulated:** measured: the Mac's watts; live: ISO prices and mix; recorded: the EIA-930 data the
  replays fetch; labelled estimates at grid scale; labelled what-ifs; an illustrative feeder layout on the city map.
  Clear, but the README's first claim "Nothing on screen is simulated" sits two paragraphs above "what-if" and "the
  feeders are an illustrative layout": better "nothing on screen is invented; what-ifs, estimates and the
  illustrative feeder layout say so".
- **Impact:** **not answerable from the README.** Organizers asked for impact (lives, money). The README has laptop
  watts, "fractions of a cent" and "the same loop at 50 MW", but no number for what Griddy would have freed in Uri or
  how many people that is; that only appears on screen during a replay. One sentence with the replay's own estimate,
  labelled, would answer it.
- **How to check a number:** `make verify`, mentioned once in the intro; every table links its evidence report.
  Good, but `make verify` is missing from "Run it" and needs a Mac-free instruction.

## Questions the README did not answer
1. How do I run anything without an Apple-silicon Mac? ("Run it" is Mac-only; verify, tests and evals need no Mac,
   but the README does not say so or how: uv install, no make on Windows.)
2. What is the impact in people or money at the scale of a real event? (see above)
3. Who is the customer? No operator or FDE quote, no named user (DEMO and docs/judging cover it; the README does not).
4. "planned ✅" in the first proof table: planned by whom, met or not? (D 03:35 explains; the README does not.)
5. The evals line says "86/90 live, all 12 injection attempts rejected"; `python -m evals` shows 121 cases and 16
   injections. Which is current? (The live run is the 02:33 one of the old suite; say so.)

## Numbers I could not trace from the README
None that matter: every table links its evidence report or names a DECISIONS entry, and `verify.py` recomputed all 74
published measured numbers. "84 % of capped seconds" (docs/devpost.md) differs from DECISIONS 14:16's 80 %; the
15:15 entry records the correction.

## What I would score, and why (Microsoft "Built for the Real World", 1-5)
- **Measurable usefulness: 4.** Real measured cuts with a naive baseline and a recompute script; held back by laptop
  scale and no impact number in the README.
- **Responsible design: 5.** The LLM has no knob path, approvals gate the risky action, injections are refused by
  rules, failures (the void run, the failed chat run) are published, numbers recompute.
- **End-to-end: 4.** Live feeds to measured watts with an audit trail; Application Insights spans were not
  verifiable by me.
- **Path to production: 3.** Described (docs/judging/production.md) but not shown in the README; one machine.
- **Customer understanding: 2-3 from the repo alone.** No customer voice in the README.
- **Reproducibility for a judge without a Mac: 2** today (uv, make, the fcntl collection error); 4 once fixed.

## Fixes, in order of judge impact (all machine 1's files)
1. `meter/powermetrics.py:11`: import `fcntl` inside the lock code (or skip the lock off macOS), so `pytest -q` runs on
   Windows; or `pytest.importorskip("fcntl")` in tests/test_meter.py. Today a Windows judge sees zero tests.
2. README: a "Check it without a Mac" block: install uv, `uv sync --extra dev`, `uv run python scripts/verify.py`,
   `uv run pytest -q`, `uv run python -m evals` (all no network, no keys).
3. README: one labelled impact sentence from a replay (freed MW and people at the event's own ratio, "estimate").
4. README: "Nothing on screen is invented" instead of "simulated"; say the evals line is the 02:33 live run.
