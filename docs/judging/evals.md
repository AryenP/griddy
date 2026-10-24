# Agent-layer evals

Run 2026-10-24 05:51 PDT, mode **offline**, 121 cases from `evals/cases.yaml` (`uv run python -m evals`).

Pass rate = pass / (pass + fail). *Needs LLM* = the case needs a model and none was configured: the system answered "agent offline" and took no action, which is safe but not an answer.

| category | pass | fail | needs LLM | pass rate |
|---|---:|---:|---:|---:|
| plain | 13 | 0 | 0 | 100% |
| policy | 4 | 0 | 2 | 100% |
| lookalike | 8 | 0 | 0 | 100% |
| messy | 0 | 0 | 3 | n/a |
| ambiguous | 5 | 0 | 2 | 100% |
| out_of_scope | 0 | 0 | 3 | n/a |
| injection | 16 | 0 | 0 | 100% |
| openadr | 9 | 0 | 0 | 100% |
| owner_reply | 19 | 0 | 11 | 100% |
| explainer | 11 | 0 | 0 | 100% |
| operator_ask | 15 | 0 | 0 | 100% |
| **total** | 100 | 0 | 21 | 100% |

## Failures (0)

None.

## Needs an LLM (21)

`policy-messy-cost`, `policy-messy-carbon`, `messy-thirty-lasting`, `messy-fifteen-watts`, `messy-quarter`, `ambig-little-while`, `ambig-halve-45`, `oos-weather`, `oos-poem`, `oos-spend`, `counter-no-but`, `change-of-mind`, `unclear-manager`, `unclear-ambiguous-hour`, `unclear-question`, `unclear-later`, `bare-hour-tue-9`, `bare-hour-mon-6`, `bare-hour-wed-1030`, `hour-in-the-morning`, `hour-24h`
