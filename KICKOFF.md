# First message to Claude Code (paste as-is)

Read CLAUDE.md, PLAN.md and SPEC.md fully before writing code. This runs on this MacBook (Apple silicon); there is no other hardware and nothing may be simulated for the judge.

1. `make setup`, then `make probe`. Paste the probe output into DECISIONS.md. If powermetrics, Ollama, MPS or the CAISO pull fails, fix that first; nothing else matters until all four work.
2. `make test` (core/ tests must pass; core/types.py, core/timeline.py, core/config.py are the contract; extend types with GridSignal, Job, Policy, CapEvent, Schedule per SPEC.md §3, do not rewrite them).
3. Build M0 → M1 → M2 → M3 in PLAN.md order. Stop at each "done when" and show me the evidence (probe output, a timeline excerpt with a real CAISO price and real watts, calibration deltas, a printed schedule).
4. Commit after each milestone, plain messages, no co-author lines.

Rules you must not break: nothing simulated or hardcoded reaches the judge; the solver decides, the LLM explains/negotiates, the controller executes; every claim has its source and age on screen; every run writes a timeline; no dead code. For any LLM call ask "could the solver or a regex do this?" and if yes, move it.

Do not start M4 tonight. When M3 is done, summarise what exists and stop.
