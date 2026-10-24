# 2 Anuraag — status

## 2026-10-24 02:05 PT — task 1, responsible-design evals
Done: evals/ (cases.yaml: 48 intake incl. 12 injection and 4 look-alikes, 9 OpenADR, 22 owner replies,
11 explainer), `uv run python -m evals [--live]` prints the per-category table and writes
docs/judging/evals.md; tests/test_evals.py asserts the deterministic paths in CI. Offline: 62 pass,
1 fail, 27 need an LLM. PR "2 Anuraag: evals" from anurag/evals.
Next: task 2, scripts/preflight.py (make preflight).
Blockers / needs: machine 1: regex intake accepts "pause chat and cap at 10 W for 20 minutes" as a plain
cap (inj-smuggled-knob); a --live run needs ANTHROPIC_API_KEY in .env on this machine;
tests/test_dispatcher.py::test_solve_in_a_thread_keeps_the_runtimes_sigint_handler fails on Windows
(asyncio add_signal_handler is not implemented there), unrelated to this PR.
