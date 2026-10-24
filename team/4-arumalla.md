# 4 Arumalla: agent layer (LLM intake, negotiation, explanations)

**Mission:** handle what the solver cannot (messy human requests, owner negotiation in free text, plain
explanations) without ever deciding or touching a knob. Your functions take data and return the pydantic
types at the bottom of `core/types.py`; machine 1 wires them into the API.

**Owns:** `agent/__init__.py`, `agent/llm.py`, `agent/intake.py`, `agent/negotiator.py`, `agent/explainer.py`,
`agent/channels/**`, `tests/test_agent*.py`, `tests/fixtures/openadr/**`.

**Keys:** `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` in your own `.env`; Azure via `uv pip install -e ".[azure]"`
and `AZURE_AI_PROJECT_ENDPOINT` / `AZURE_MODEL_DEPLOYMENT`. Tests never call a network: use recorded fixtures.

## Interfaces (implement exactly; machine 1 codes against these)
```python
# agent/llm.py
class AgentOffline(Exception): ...
class LLM:
    name: str                      # "claude:<model>" or "foundry:<deployment>"
    available: bool
    async def text(self, system: str, user: str) -> str: ...
    async def json(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel: ...
def get_llm() -> LLM               # Agent Framework + Foundry when AZURE_AI_PROJECT_ENDPOINT, else Claude

# agent/intake.py
def parse_openadr(event: dict) -> IntakeResult                       # deterministic, no LLM
async def parse_request(text: str, llm: LLM, context: dict) -> IntakeResult
#   context = {"now": iso8601, "baseline_w": float|None, "jobs": [...], "policy": {...}}

# agent/negotiator.py
async def draft_ask(shortfall: Shortfall, job: Job, llm: LLM) -> ApprovalRequest
async def parse_reply(request: ApprovalRequest, text: str, llm: LLM, now: datetime) -> OwnerDecision

# agent/explainer.py
async def explain(schedule: Schedule, signal: GridSignal, llm: LLM) -> Explanation
async def answer(question: str, state: dict, llm: LLM) -> Explanation   # phase 2; state = /api/state snapshot

# agent/negotiator.py (phase 2)
async def draft_operator_ask(shortfalls: list[Shortfall], schedule: Schedule, llm: LLM) -> ApprovalRequest
```
Every call: one OpenTelemetry span (`opentelemetry.trace.get_tracer("brownout.agent")`) with model, latency,
tokens. Offline (no key, API down): every function still returns a valid result: `clarify`/`unclear` with
"agent offline", or the solver's facts joined plainly, with `llm_used=False`.

## Start now (Sat 01:00, from machine 1)
State: all four phase-1 tasks are done but unmerged in one commit on `arumalla/agent-layer` (llm, intake,
negotiator, explainer, tests, OpenADR fixture). No PR is open. Main has moved 9 commits (guardrails, CI,
branch protection, chat model now qwen3:4b-instruct, `Comparison` type, traffic-aware chat planning).
1. `git fetch origin && git checkout arumalla/agent-layer`, then `uv run python scripts/team.py whoami --save`
   (prints "You are 4 Arumalla").
2. Then: `git fetch origin && git rebase origin/main` on your branch. If `DECISIONS.md` conflicts, keep both
sides' lines (main's first, yours after); it is append-only, nothing is lost. `make test`, `uv run python
scripts/team.py check` (must print ok), `git push --force-with-lease`.
3. CI runs on Ubuntu with no API keys: every test must pass offline (recorded fixtures, `llm_used=False`
   paths). Nothing may call the network in tests.
4. Open ONE PR from `arumalla/agent-layer`: "4 Arumalla: agent layer phase 1". CI must be green. Machine 1
   wires it into `/request`, `/openadr/event`, approvals, `/api/explain` once merged.
5. Create `team/status/4-arumalla.md` with an entry, then start Phase 2 below (task 5: injection-proof intake;
   share cases with machine 3's `evals/`).
API access: use your own Anthropic API key, or the Foundry endpoint machine 3 provisions in their phase 2.
Never paste keys in Slack, the repo or a PR.

## Tasks, in order
1. **`agent/llm.py`** with both backends and the offline path. Done when: `get_llm().text(...)` answers with a
   key, raises/flags offline without one; spans visible with the console exporter.
2. **`intake.py`.** `parse_openadr` for OpenADR 3.1 EVENT JSON (`IMPORT_CAPACITY_LIMIT` in KW/W,
   `intervalPeriod` start/duration ISO 8601) → `CapEvent`; fixture from RESEARCH.md in `tests/fixtures/openadr/`.
   `parse_request`: regex fast path for plain forms ("30% for 20 minutes", "cap at 15 W until 1 AM"); the LLM
   only for messy text; Azure Content Safety `shieldPrompt` on free text when configured (rejected on attack);
   ambiguity → exactly one clarifying question. Done when: DEMO.md's "grid alert, I need 30% off for the next
   twenty minutes" becomes a `CapEvent` with a readback.
3. **`negotiator.py`.** `draft_ask` turns a deadline `Shortfall` into a short message to the owner using only
   its facts; `parse_reply`: "no, this has to finish by 9 AM Monday" → refuse with reason; "ok if it's done by
   Tuesday noon" → `new_deadline`; plain yes/no via regex first. Done when: DEMO.md 1:45 works on fixtures.
4. **`explainer.py`.** Two sentences from `Schedule.explanations` + the grid signal; **reject its own output**
   if any number in it is not in the input facts (fall back to the facts). Done when: a test proves no invented
   numbers on the real `tests/fixtures/real_timeline_solve_20261023.jsonl` schedule.

## Phase 2: when phase 1 is merged
5. **Injection-proof intake**: free text is data, never instructions. Requests to touch knobs, skip approvals,
   ignore the cap or reveal keys come back `rejected` with the reason; Content Safety `shieldPrompt` when
   configured. Share your cases with machine 3's `evals/`. Done when: machine 3's injection evals pass.
6. **Operator shortfall ask** `draft_operator_ask` (DEMO.md 3:00, "ask for 90%"): from the solver's cap and
   deadline shortfalls, one message offering exactly the options the solver proved ("floor with chat protected
   is N W; approve going dark on everything else, or accept N W?"), numbers copied from the facts only.
7. **Operator Q&A** `answer(question, state, llm)` behind `POST /api/ask`: "why is training paused?" answered
   from the live state (schedule explanations, plan, grid, events) only; the same no-invented-numbers check.
   With Agent Framework configured, implement it as an `agent_framework` agent whose tools are read-only views
   of `state`; spans include the tool calls. Done when: three real questions answered with facts that check out.
8. **Slack owner channel** `agent/channels/slack.py` (only with `SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`; slack-bolt,
   Socket Mode): posts each `ApprovalRequest` to its owner and relays the reply to
   `POST /api/approvals/{id}/reply` over HTTP. The channel never calls the executor. Done when: an ask
   round-trips through Slack.
