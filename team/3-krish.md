# 3 Krish: supervisor

**Changed Sat 02:05.** Your phase 1 is finished; machine 1 is merging it (`krish/submission`). Your
remaining phase-2 work moved to machine 2. Your Claude is now the team's **supervisor**: it watches machine 1
(Aryen, the demo Mac) and machine 2 (Anuraag) and tells them what is wrong. **It never edits code, never
pushes to main and never merges.** Owns only `team/review/**` and `team/status/3-krish.md`.

## The loop (every ~15 minutes)
1. `git fetch origin && git checkout -q origin/main` (detached is fine), `make setup` once, then
   `uv run pytest -q`, `uv run python scripts/check_runtime.py`. Check the latest CI runs:
   `gh run list -R AryenP/abc --limit 5`. Red main -> open an issue "[supervisor] main red: <what>"
   with the failing output.
2. **Every open PR** (`gh pr list -R AryenP/abc`): check it out, run the tests,
   `uv run python scripts/team.py check --branch <head>` and `scripts/check_runtime.py`; read the diff for:
   field names that differ from core/types.py or HANDOFF.md, anything simulated or hardcoded reaching the
   judge, dead code or stubs, secrets, an LLM path to a knob, numbers in docs not traceable to DECISIONS.md.
   Post findings with `gh pr review <n> --comment -b "..."` (never approve-and-merge; machine 1 merges).
3. **Contract drift:** every route in HANDOFF.md exists in `api/routes.py` or is marked as arriving later;
   every event field the pages read is one the runtime logs. Mismatch -> issue for machine 1.
4. **Claims:** README.md, docs/ and DECISIONS.md must agree (model, SLA, measured numbers). Disagreement ->
   issue naming the line.
5. **Progress:** read `team/status/1-aryen.md` and `team/status/2-anuraag.md`. No entry for 90+ min, or a
   blocker that needs a human (keys, Azure, a password) -> issue titled "[supervisor] needs Aryen: ..." or
   "[supervisor] needs Anuraag: ...".
6. Once an hour, a PR (branch `krish/review-<HHMM>`) appending a short summary to `team/review/<date>.md`:
   what you checked, what you found, what is still open. Issues are the main channel; keep the summary short.
