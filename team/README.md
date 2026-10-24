# Brownout team: four machines, one repo

New session on any machine? Start at `KICKOFF.md` in the repo root.

| # | Who | Role | GitHub | Branches | Assignment |
|---|---|---|---|---|---|
| 1 | Aryen | **The demo Mac**: runtime, integration, frontend, agent (with subagents) | AryenP | `main` | [1-aryen.md](1-aryen.md) |
| 2 | Anuraag | Evals, judging docs, pre-demo preflight | ARP-source | `anurag/<task>` | [2-anuraag.md](2-anuraag.md) |
| 3 | Krish | Supervisor: reviews PRs, CI, contract drift and claims; never edits code | krishteli | `krish/review-<HHMM>` | [3-krish.md](3-krish.md) |
| 4 | Arumalla | Paused Sat 01:45 (agent layer phase 1 merged; machine 1 continues it) | MauryaAru | — | [4-arumalla.md](4-arumalla.md) |

How the pieces meet:
```
 2 web/*  ──HTTP + /ws (HANDOFF.md contract)──▶  1 api/* ── executor ── knobs ── workloads (this Mac)
                                                    │  wires, calls, never the reverse
                         4 agent/{llm,intake,negotiator,explainer}.py   3 agent/reporter.py · telemetry/ · scripts/compare.py
                                    └──── both return the pydantic types at the bottom of core/types.py ────┘
```

## One-time setup on each laptop (5 minutes, the human does this)
1. **Your own Claude account only.** Each person drives their own account; never log in as, or run work
   through, a teammate's account to use their quota (Anthropic's terms forbid sharing accounts). All of your
   sessions, local and cloud, draw on your own 5-hour and weekly limits: send long jobs to the biggest plan.
2. **Update and pin.** `claude update`, then `claude --version` (machine 1 is on 2.1.310; hooks need a recent
   build). In Claude Code run `/model` and pick the strongest model your plan allows; do not leave it on a
   cheaper default.
3. `git clone https://github.com/AryenP/abc.git brownout && cd brownout && cp .env.example .env`, `make setup`.
4. `uv run python scripts/team.py whoami --save` (or `--member N --save`). This writes the gitignored
   `.claude/member.local` the lane-guard hook reads; without it the hook blocks every edit and tells you why.
5. More than one Claude session on your laptop? Give each its own worktree: `git fetch origin` first (or the
   worktree starts from a stale main), then `claude -w <task>`. `.worktreeinclude` copies `.env` and your
   identity. Only one `make demo`/`chat-sweep` per laptop: ports 8080 and 8090 are shared.

## Rules for every machine
1. **Own your files, only your files.** `team/roster.yaml` lists them. `uv run python scripts/team.py check`
   must print `ok` before every push. Need something in another person's file (a route, a type, a
   config field)? Write it under "Needs from others" in your PR description; the owner does it.
2. **One branch per task**, your prefix, PR into `main`. Machine 1 reviews and merges. Plain commit
   messages, no co-author lines. `make test` green before every PR.
3. **Contract first.** Code against the HANDOFF.md API contract and the team types in `core/types.py`
   exactly. If a contract is wrong, say so in the PR; do not invent fields.
4. **Nothing simulated reaches the judge.** Fakes only in `tests/`, labelled. No demo/mock/replay modes.
   Real captured timelines for development: `tests/fixtures/real_timeline_*.jsonl`.
5. **The LLM never touches a knob.** Agent code returns data; machine 1 decides what the runtime does
   with it. For every LLM call ask "could the solver or a regex do this?" If yes, do that instead.
6. **Every claim shows its source and age. No dead code, no stubs, no secrets** (`.env` only).
7. Only machine 1's measurements are demo numbers. Anything measured elsewhere is development data.
8. Append to `DECISIONS.md` (never edit old lines) when you decide something SPEC.md does not say.
9. **Status, not memory.** Before every PR and before stepping away or hitting a limit, append an entry to
   your own `team/status/<n>-<name>.md` (create it on first use; format below). One file per person, so
   these never conflict.
   ```
   ## <YYYY-MM-DD HH:MM PT> — <task from your assignment file>
   Done: <what landed, PR number>
   Next: <the next task or step>
   Blockers / needs: <from whom, what> or none
   ``` Lessons everyone needs go to machine 1 for CLAUDE.md, because Claude's memory stays on one laptop.
10. **CI guards main.** Every PR runs the tests, the fabricated-data scan (`scripts/check_runtime.py`) and the
   ownership check by branch prefix. A red PR is not merged. Machine 1 merges one PR at a time.
11. **Demo from a tag.** When a full live `make demo` works, machine 1 runs `make tag-stable`; the table demo
   runs from the newest `demo-stable-N`, never from whatever main is at 10:29.
12. **Slack format** for merges: `[<n> <name>] merged #<PR>: <what changed> / contract changes: none | <what>`.
   Contract changes (HANDOFF.md, the types in core/types.py) are announced before they are pushed.
13. **Plans grow.** Machine 1 adds phases to your assignment file as work lands. Pull main before every
   task; when your current phase is merged, continue with the next phase in the same file.

## The prompt (same for every machine; paste as-is into Claude Code in the repo folder)
```
You are one of four machines building Brownout. First run:
  uv run python scripts/team.py whoami
It prints your number, name, role and assignment file. If it cannot tell, ask me which number I am
(1 Aryen, 2 Anuraag, 3 Krish, 4 Arumalla) and use --member N from then on.

Then run `uv run python scripts/team.py whoami --save` so the lane-guard hook knows you. Read,
fully and in this order: CLAUDE.md, team/README.md, your assignment file, your team/status file,
HANDOFF.md, SPEC.md, DECISIONS.md (PLAN.md and DEMO.md for context). Your assignment file is your plan: do its
"Start now" section first if it has one, then follow its task order and stop at each task's "done when" to show me the evidence before the next task.

Setup if not done: `make setup` then `make test` (must be green). Work only on files your roster
entry owns; run `uv run python scripts/team.py check` before every push (must print ok). One branch
per task with your prefix, small commits with plain messages and no co-author lines, then push and
open a PR into main titled "<your number> <name>: <task>" with sections: What, How tested, Needs
from others. Before the PR, append done/next/blockers to your team/status file; after it, make sure CI
is green. Pull main (`git pull --rebase origin main`) before starting each task, and re-read your
assignment file after pulling: machine 1 adds new phases there. When a phase is done, start the next.

Never break: nothing simulated or hardcoded reaches the judge; the solver decides, the LLM explains
and negotiates, the controller executes; every claim has its source and age on screen; every run
writes a timeline; no dead code or stubs; no secrets in the repo. When unsure whose file something
is: `uv run python scripts/team.py owner <path>`.
```
