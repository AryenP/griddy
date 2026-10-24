# Brownout team: four machines, one repo

| # | Who | Role | GitHub | Branches | Assignment |
|---|---|---|---|---|---|
| 1 | Aryen | Runtime and integration, **the demo Mac** | AryenP | `main` | [1-aryen.md](1-aryen.md) |
| 2 | Anuraag | Frontend: dashboard, phone pages, receipts screen | ARP-source | `anurag/<task>` | [2-anuraag.md](2-anuraag.md) |
| 3 | Krish | Proof and production: report, comparison, telemetry, Azure, submission | krishteli | `krish/<task>` | [3-krish.md](3-krish.md) |
| 4 | Arumalla | Agent layer: LLM, intake, negotiator, explainer | MauryaAru | `arumalla/<task>` | [4-arumalla.md](4-arumalla.md) |

How the pieces meet:
```
 2 web/*  ──HTTP + /ws (HANDOFF.md contract)──▶  1 api/* ── executor ── knobs ── workloads (this Mac)
                                                    │  wires, calls, never the reverse
                         4 agent/{llm,intake,negotiator,explainer}.py   3 agent/reporter.py · telemetry/ · scripts/compare.py
                                    └──── both return the pydantic types at the bottom of core/types.py ────┘
```

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

## The prompt (same for every machine; paste as-is into Claude Code in the repo folder)
```
You are one of four machines building Brownout. First run:
  uv run python scripts/team.py whoami
It prints your number, name, role and assignment file. If it cannot tell, ask me which number I am
(1 Aryen, 2 Anuraag, 3 Krish, 4 Arumalla) and use --member N from then on.

Then read, fully and in this order: CLAUDE.md, team/README.md, your assignment file, HANDOFF.md,
SPEC.md, DECISIONS.md (PLAN.md and DEMO.md for context). Your assignment file is your plan; follow
its task order and stop at each task's "done when" to show me the evidence before the next task.

Setup if not done: `make setup` then `make test` (must be green). Work only on files your roster
entry owns; run `uv run python scripts/team.py check` before every push (must print ok). One branch
per task with your prefix, small commits with plain messages and no co-author lines, then push and
open a PR into main titled "<your number> <name>: <task>" with sections: What, How tested, Needs
from others. Pull main (`git pull --rebase origin main`) before starting each task.

Never break: nothing simulated or hardcoded reaches the judge; the solver decides, the LLM explains
and negotiates, the controller executes; every claim has its source and age on screen; every run
writes a timeline; no dead code or stubs; no secrets in the repo. When unsure whose file something
is: `uv run python scripts/team.py owner <path>`.
```
