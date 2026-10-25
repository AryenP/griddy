# 2 Anuraag — status

## 2026-10-24 02:05 PT — task 1, responsible-design evals
Done: evals/ (cases.yaml: 48 intake incl. 12 injection and 4 look-alikes, 9 OpenADR, 22 owner replies,
11 explainer), `uv run python -m evals [--live]` prints the per-category table and writes
docs/judging/evals.md; tests/test_evals.py asserts the deterministic paths in CI. Offline: 62 pass,
1 fail, 27 need an LLM before the intake hardening; on main after it (f9e985c): 73 pass, 0 fail, 17 need an
LLM (11/12 injections rejected deterministically). PR #3 "2 Anuraag: evals" from anurag/evals.
Next: task 2, scripts/preflight.py (make preflight).
Blockers / needs: a --live run needs ANTHROPIC_API_KEY in .env on this machine;
tests/test_dispatcher.py::test_solve_in_a_thread_keeps_the_runtimes_sigint_handler fails on Windows
(asyncio add_signal_handler is not implemented there), unrelated to this PR.

## 2026-10-24 02:40 PT — task 7 preflight (PR #4) and F1 operator console (PR #5)
Done: PR #3 (evals) and PR #4 (scripts/preflight.py, make preflight) merged. F1: web/operator.js for
operator.html (POST /request with dictation as a checked transcript, POST /openadr/event, cap events with a
countdown and time to compliance from the 10-s mean of measured watts, power_cap approvals, POST /api/ask,
current slot planned vs cap). Checked at 375 px on the real calibrate capture: 12 s to compliance. PR #5.
Next: F2 receipts view in the dashboard (anurag/receipts).
Blockers / needs: machine 1: active CapEvents in the snapshot; a distinct kind for {intake, who} events;
a live run of the operator page on the demo Mac. make preflight once on the demo Mac.

## 2026-10-24 03:20 PT — F2 receipts view in the dashboard
Done: PR #5 (operator console) merged. F2: a Receipts section on the dashboard (web/receipts.js): run
pickers from GET /api/runs, the Report (reduction, time to compliance, before/during W, energy, cost,
carbon, TTFT p95, deadlines, approvals with who/when/decision, caveats), the Comparison table with
differences and notes, and the /api/trace spans as the audit trail. Missing routes or runs say
"not available yet: <route>"; an unpriced window says "not priced" instead of 0. PR "2 Anuraag: receipts".
Next: F3 scripts/qr.py, then F4 design pass.
Blockers / needs: a live look on the demo Mac with real runs (this machine only has the fixtures).
## 2026-10-24 03:30 PT — F3 scripts/qr.py (make qr)
Done: F2 receipts in review (PR #6). F3: make qr prints terminal QR codes and saves reports/qr/{chat,owner,
operator}.png for PUBLIC_URL + /chat, /owner.html, /operator.html; refuses a loopback or non-URL PUBLIC_URL
with the fix. Ran it on this machine's LAN IP. PR "2 Anuraag: qr".
Next: F4 design pass across all pages (after #6 merges: it touches style.css).
Blockers / needs: none.

## 2026-10-24 03:45 PT — follow-ups to machine 1's 03:15 server changes
Done: PRs #6 (receipts) and #7 (make qr) merged. Follow-ups: dashboard logs the new `intake` kind;
operator page seeds caps from the snapshot's `cap_events` and tracks the plan; both show "Cap held while
the operator decides" from plan.needs_approval + the solver's "running plan:" fact (common.js
runningPlanLine). PR "2 Anuraag: intake and cap-held follow-ups".
Next: F4 design pass with the 24-h dispatch map as centrepiece.
Blockers / needs: none.

## 2026-10-24 04:05 PT — F4 design pass: the 24-h dispatch map
Done: PR #8 merged. F4: web/map.js, a 24-h dispatch map as the dashboard's centrepiece (price line, hour
marks, cap bands with their W, one row per job: solid GPU / hatched CPU / recessed deferred, plan watts vs
cap, the current slot outlined through every row, tooltips with the slot's price, cap and the solver's facts
for that job). Chart.js removed (nothing external to fetch for the map). Control-room tokens in style.css
:root and Barlow (one family, system fallback) on every page. Checked at 1440 and 375 px on the real solve
capture. PR "2 Anuraag: design pass and dispatch map".
Next: F5 polish (hotkeys, captions, layout jumps), then judging docs.
Blockers / needs: none.

## 2026-10-24 04:20 PT — F5 polish
Done: PR #9 (design pass, dispatch map) merged. F5: dashboard hotkeys D (dispatcher), 1/2/3 (objective),
R (receipts) with a key legend in the header; a one-line "what you're seeing" caption on the map, why-this-plan,
event log and receipts panels; the map reserves its height so the page does not jump when the schedule
arrives. Operator E/A hotkeys were already in. PR "2 Anuraag: polish".
Next: 8 judging docs, then 10 proof page.

## 2026-10-24 05:05 PT — task 10 proof page
Done: judging docs in review (PR #11). Task 10: web/proof.html + proof.js: the newest run of each policy
(ignore the call, pause everything, Brownout) from GET /api/runs, their measured watts from
/api/runs/{id}/series drawn on one axis aligned at each cap start with Brownout's cap as the red line,
Brownout vs each other policy from /api/compare, and what each run did; "recorded, not live" on every block.
Rendered from tests/fixtures/evidence3 at 1440 and 375 px. tests/test_web_proof.py. PR "2 Anuraag: proof page".
Next: 16 load outside the plan (after PR #10), then 11 evals.
Blockers / needs: none.

## 2026-10-24 04:45 PT — task 8 judging docs
Done: F5 polish in review (PR #10, CI fixed by merging main). Task 8: docs/judging/{criteria,production,
compliance,responsible,customer}.md; every number cited to a DECISIONS.md timestamp or RESEARCH.md section
(checked with grep), "to be measured" where it is not measured, quote "to be collected". Re-ran the offline
evals on current main: 74 pass, 0 fail, 16 need a model, injections 12/12 (docs/judging/evals.md).
PR "2 Anuraag: judging docs".
Next: 10 proof page; 16 load outside the plan after PR #10 merges.
Blockers / needs: the operator/FDE quote (Aryen).

## 2026-10-24 05:44 PT — task 18 preflight fixes (cloud session for machine 2)
Done: check_sudo probes the exact powermetrics line the sudoers rule allows (same as the Makefile's SUDO_PM),
not `sudo -n true`; the demo-tag FAIL hint says "tag this commit once the rehearsal passes: make tag-stable"
(the newest tag moves to the detail). Tests cover both. PR "2 Anuraag: preflight fixes".
Next: 17 remove the old dashboard rules from style.css, then 11 evals.
## 2026-10-24 05:48 PT — task 17 old dashboard rules out of style.css
Done: removed .numbers, .jobs, .jobs .tile, .tile, .numbers .tile, .big .value (both), .job, .toggle,
.toggle.off. Kept .top, .claim p, .row, .bottom (proof.html uses them) and .job-head (owner.js). Pixel-identical
screenshots of chat/owner/operator/proof at 1440 and 375 px; on the dashboard every HTML element's computed
style is identical (only the clock-driven SVG hour labels move between runs). PR "2 Anuraag: style cleanup".
Next: 11 evals for tonight's agent changes.
Blockers / needs: none.
## 2026-10-24 05:51 PT — task 11 evals for tonight's agent changes
Done: 31 new cases in evals/cases.yaml: claimed grants in intake (4, all rejected by the guard) and 4 look-alikes
that stay cap events; bare hours in owner replies (3 must be unclear with the AM/PM question) and 5 with the
half of the day said; a new `operator_ask` category over agent.explainer.answer on the real solve + a real
powermetrics sample (7 steering questions refused, 2 answered without promising anything, 6 legit questions
answered from the facts), each answer checked for invented numbers and promised actions. Offline: 100 pass,
0 fail, 21 need a model (docs/judging/evals.md). operator_ask is asserted in CI. PR "2 Anuraag: evals for
tonight's agent changes".
Next: --live re-run on a machine with ANTHROPIC_API_KEY (none in this cloud session); 13 accessibility.
Blockers / needs: machine 1: parse_reply asks the AM/PM question only after the LLM answers new_deadline, so
offline "ok if it's done by Tuesday 9" comes back "agent offline" though `ambiguous_hour` (a regex) could ask it.

## 2026-10-24 05:55 PT — task 13 accessibility pass
Done: tests/test_web_a11y.py: WCAG AA contrast for 31 text/background and graph-mark pairs from the style.css
:root tokens (badges composited over their panel), and every `color:` in style.css must be in that list.
Two failures fixed: white on --action was 3.22:1 (now #2f6fe0, 4.7:1) and the map's plan-W bars were 2.56:1
(now #5a7596, 3.38:1). aria-live="polite" (additions only) on the owner and operator approval boards, polite
on the operator's three result boxes; aria-labels on the operator textareas and the chat box; keyboard order
asserted on operator and owner. Stacked on PR #17. PR "2 Anuraag: accessibility".
Next: 12 failure drills (needs a machine with Ollama and the server; this cloud session can record the grid,
agent-offline and meter-missing rows only).
Blockers / needs: machine 1: dashboard.css draws its plan bars in #4a6280 too (2.56:1 on the panel).
## 2026-10-24 05:58 PT — task 19 operator page: replay the evening peak (simulated)
Done: a "Simulated neighbourhood" block on operator.html (dashed edge, SIMULATED badge, one line on what is
real): a button and the N hotkey POST /api/neighbourhood start/stop; from the `neighbourhood` WS events
(only those with simulated: true) it shows the simulated clock, line loading of limit_kw, diesel kW, diesel kWh
vs Brownout off and kWh avoided, and our sites' measured watts; STALE after 15 s. The cut it triggers is a
real CapEvent, so Active cap events and time to compliance are unchanged. /api/neighbourhood added to
CONTRACT_ROUTES; a test asserts every number is labelled simulated or measured. Rendered at 375 and 1440 px
from contract-shaped messages (no horizontal scroll). PR "2 Anuraag: neighbourhood replay".
Next: 14 architecture diagram with the simulated neighbourhood, then 15 driver card.
Blockers / needs: a run against make demo on the demo Mac (this cloud session has no calibration or meter).
## 2026-10-24 06:03 PT — task 14 architecture diagram
Done: docs/judging/architecture.svg, hand-written, 1200x800, light background: ISO feeds -> GridWatcher ->
CP-SAT solver -> Schedule -> Executor -> knobs -> workloads; powermetrics -> meter -> timeline -> receipts;
owner/operator approvals through the negotiator; the LLM agent beside the solver with arrows only to intake,
explanations and negotiation, and "agent/ returns data only: no code path to the executor or a knob" (checked:
agent/ imports nothing from controller/). The simulated neighbourhood in a dashed box with its config numbers
(config/neighbourhood.yaml), our measured response in, the utility's cut out to the real solver. Every box names
its file. PR "2 Anuraag: architecture diagram".
Next: 15 driver card.
Blockers / needs: machine 1 links it from README.md and docs/devpost.md.
## 2026-10-24 06:04 PT — task 15 driver card
Done: docs/judging/driver-card.md, one printable page: tag check, make preflight / demo / qr, the page URLs,
every hotkey (dashboard D 1 2 3 R; operator E A N), the four minutes from DEMO.md with the exact clicks and
what to say, the optional neighbourhood replay with its "simulated" line, and a truthful line for each failure
(stale feed, Ollama, agent offline, no meter, odd input, Application Insights lag). No numbers beyond what the
screen shows. PR "2 Anuraag: driver card" (the N hotkey arrives with PR #20).
Next: 12 failure drills.

## 2026-10-25 01:16 PT — Fetch.ai three-agent flow (FA1-FA6)
Done: fetch_agents/{common,grid_desk,facility,verifier}.py on anurag/fetch-three-agents. Grid Desk reads a cut by
rule and relays each step; Facility makes only POST /request (source "fetch") and GET /api/approvals, never applies,
and stops if a response is not staged; Verifier reads the run's timeline with the standard library and matches
agent/reporter.py exactly on all 10 committed evidence runs (run of record: 14.34 W, 93 %, 12 s). No LLM anywhere.
tests/test_fetch_three.py (54 tests, fakes only); docs/judging/fetch-three-agents.md. Checked on real uagents 0.26.1
in the pinned env: addresses from seeds, message digests identical across agents, protocols build.
pytest 555 passed. PR "2 Anuraag: Fetch three-agent flow".
Next: FA7 on the demo Mac once machine 1's staged POST /request and make fetch-three land.
Blockers / needs: machine 1 (staged /request contract, make fetch-three, .env.example lines); Aryen (Agentverse key).
