# Agent-layer evals

Run 2026-10-24 03:56 Pacific Daylight Time, mode **offline**, 90 cases from `evals/cases.yaml` (`uv run python -m evals`).

Pass rate = pass / (pass + fail). *Needs LLM* = the case needs a model and none was configured: the system answered "agent offline" and took no action, which is safe but not an answer.

| category | pass | fail | needs LLM | pass rate |
|---|---:|---:|---:|---:|
| plain | 13 | 0 | 0 | 100% |
| policy | 4 | 0 | 2 | 100% |
| lookalike | 4 | 0 | 0 | 100% |
| messy | 0 | 0 | 3 | n/a |
| ambiguous | 5 | 0 | 2 | 100% |
| out_of_scope | 0 | 0 | 3 | n/a |
| injection | 12 | 0 | 0 | 100% |
| openadr | 9 | 0 | 0 | 100% |
| owner_reply | 16 | 0 | 6 | 100% |
| explainer | 11 | 0 | 0 | 100% |
| **total** | 74 | 0 | 16 | 100% |

## Failures (0)

None.

## Needs an LLM (16)

`policy-messy-cost`, `policy-messy-carbon`, `messy-thirty-lasting`, `messy-fifteen-watts`, `messy-quarter`, `ambig-little-while`, `ambig-halve-45`, `oos-weather`, `oos-poem`, `oos-spend`, `counter-no-but`, `change-of-mind`, `unclear-manager`, `unclear-ambiguous-hour`, `unclear-question`, `unclear-later`
