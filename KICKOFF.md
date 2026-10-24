# Start here (every machine)

Brownout is built by four Claude Code sessions on four laptops, one per person, coordinated only through
this repo. Paste this into Claude Code in the repo folder:

```
Run `git checkout main && git pull`, then `uv run python scripts/team.py whoami --save` and tell me who
I am. Then read CLAUDE.md, team/README.md and my assignment file. Do the "Start now" section at the top
of my assignment file first, then continue with its tasks in order. Stop at each task's "done when" and
show me the evidence before the next one.
```

If `whoami` cannot tell, say which number you are: 1 Aryen, 2 Anuraag, 3 Krish, 4 Arumalla
(`uv run python scripts/team.py whoami --member N --save`). First time on this laptop: the one-time
setup in team/README.md (clone, `.env`, `make setup`, `claude update`, `/model`).

| # | Who | Plan | Status file |
|---|---|---|---|
| 1 | Aryen | team/1-aryen.md | team/status/1-aryen.md |
| 2 | Anuraag | team/2-anuraag.md | team/status/2-anuraag.md |
| 3 | Krish | team/3-krish.md | team/status/3-krish.md |
| 4 | Arumalla | team/4-arumalla.md | team/status/4-arumalla.md |

Machine 1 merges PRs, keeps HANDOFF.md (the API contract) and adds new phases to the plan files. Pull
main before every task: your plan may have grown.

Machine 1's original Friday-night kickoff (M0–M3) is in git history: `git show 640bd86:KICKOFF.md`.
