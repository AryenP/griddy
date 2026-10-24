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
