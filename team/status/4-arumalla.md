# 4 Arumalla — status

## 2026-10-24 — agent layer phase 1 (tasks 1-4)
Done: agent/llm.py (Claude + Agent Framework/Foundry + offline, OTel span per call), agent/intake.py
(OpenADR 3.1 IMPORT_CAPACITY_LIMIT -> CapEvent; regex fast path, LLM for messy text, shieldPrompt when
configured, one clarifying question), agent/negotiator.py (draft_ask from Shortfall facts; parse_reply
regex-first), agent/explainer.py (rejects numbers not in the facts). 35 offline tests. Rebased on main,
PR "4 Arumalla: agent layer phase 1" from arumalla/agent-layer.
Next: phase 2 task 5, injection-proof intake (share cases with machine 3's evals/).
Blockers / needs: machine 1 wires /request, /openadr/event, approvals, /api/explain after merge. Live LLM
answer not yet shown (no API key on this machine); run `uv run python -m agent.llm` with a key in .env.

## 2026-10-24 05:46 PT — supervisor check
Checked: main deda373, pytest 310 passed / 2 skipped, CI green (last 5), no secrets (only test placeholders),
check_runtime ok; reviewed a25c630..deda373 (fleet, neighbourhood, dashboard ratio). Simulated line is labelled
simulated in config, model, timeline and WS payload. Opened #13 (neighbourhood homes curve flat on ERCOT's
seven-day forecast) and #14 (laptop watts shown without reading age).
