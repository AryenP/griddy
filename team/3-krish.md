# 3 Krish: supervisor

## NEW (Sat 05:45): your queue for the next hours, in order. Machine 4 (Arumalla) now does the 10-minute checks
Aryen asked for you to have work. You still never edit machine 1's or 2's code: you review, verify and write
your own files (`team/review/**`, `docs/qa/**`, your status file). Real bugs go in GitHub issues titled
`[supervisor] ...` with file, line, what you expected, what you saw. Branch `krish/<task>`, then a pull request.
Since 05:35 part of the demo is SIMULATED by Aryen's decision (DECISIONS 05:45): read that entry first.

### K1. Deep review of the two new pieces (about 45 min)
`fleet/agent.py`, `fleet/hub.py`, `neighbourhood/model.py`, and their wiring in `controller/execute.py`,
`api/app.py`, `api/routes.py` (DECISIONS 05:10-05:45, HANDOFF.md). Look for real failures, for example:
a laptop that drops out while a cap is in force; a laptop that is plugged in; the neighbourhood's call for a cut
when our sites are idle (their baseline is tiny, so their "response" cannot move); the time-lapse ending while a
cap is still in force; a simulated number that reaches a page or a report without "simulated"; anything that
changes the single-Mac behaviour when no laptop and no neighbourhood are configured. Run `uv run pytest -q`.
Write `team/review/0545-fleet-neighbourhood.md` (findings, most severe first, each with file:line) and open an
issue for each real bug. Done when: the review is merged and every finding has an issue or a "not a bug" line.

### K2. The judges' hard questions: `docs/qa/judge-questions.md` (about 45 min)
15 to 20 questions a Microsoft judge is likely to ask in 4 minutes, each with a 1 to 3 sentence answer that is
true and cites its source (a `DECISIONS.md` time, a `RESEARCH.md` section, a file or a run id). Start with:
"What exactly is simulated, and what is measured?", "Why should I trust the watts?", "What happens if the AI is
wrong?", "How does this get to 50 MW?", "What did a real operator say?" (answer honestly: to be collected at
the 10 AM workshop until Aryen adds it). Never invent a number. Done when: merged.

### K3. Number audit across what judges read (about 40 min)
Every number in `README.md`, `docs/devpost.md`, `docs/judging/*.md` and `docs/evidence/*.md`: does it match the
`DECISIONS.md` line or evidence report it claims? Is anything simulated presented as measured? Write
`team/review/0545-number-audit.md` (number, where, source, matches yes/no) and open an issue per mismatch.
Done when: merged. Re-run it after the final evidence run (~07:20) lands, when README and Devpost numbers change.

### K4. If one of the Windows laptops is yours
Tell Aryen in your status file. After 07:20 you may be asked to join it to the demo: `fleet/README.md`.


**Changed Sat 02:05.** Your phase 1 is finished; machine 1 is merging it (`krish/submission`). Your
remaining phase-2 work moved to machine 2. Your Claude is now the team's **supervisor**: it watches machine 1
(Aryen, the demo Mac) and machine 2 (Anuraag) and tells them what is wrong. **It never edits code, never
pushes to main and never merges.** Owns only `team/review/**` and `team/status/3-krish.md`.

## First, once (Sat 02:00): your branch is superseded, do not open a PR from it
`krish/submission` (incl. bb58fc4 "fit reporter, compare and telemetry to main's event shapes") duplicates work
machine 1 already merged at 01:55 (`734ad2c` "Merge receipts", plus `2d7991e` wiring /api/report, /api/compare,
/api/trace). Do not merge or PR it. Instead, as your first supervisor job:
1. `git diff origin/main origin/krish/submission -- agent/reporter.py scripts/compare.py telemetry/ tests/test_report.py tests/test_compare.py tests/test_telemetry.py`
2. For every place where your fit is more correct than main's (an event field read wrongly, a number computed
   differently, a test main lacks), open an issue "[supervisor] receipts: <what>" quoting both versions. Machine 1
   fixes it on main.
3. Your status file is yours: open one small PR `krish/review-status` with only `team/status/3-krish.md`.
4. Then delete the old branches: `git push origin --delete krish/submission krish/telemetry krish/compare krish/reporter krish/emission-factors`.

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
