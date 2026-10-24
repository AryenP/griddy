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
