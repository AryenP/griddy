# Griddy's three agents on ASI:One (Fetch.ai)

A demand-response deal between three uAgents, all inside ASI:One, on the live runtime on the demo Mac. A utility
asks, a facility offers and a person approves, then an independent meter check verifies. Nothing is simulated: the
grid numbers are the runtime's live feed, the cut is Griddy's own intake and solver, the approval is the operator's
own plain "yes" (or "no, <reason>") typed in the same ASI:One chat or on the operator page, and the verdict is
computed from watts measured by macOS powermetrics. No language model makes any decision anywhere in this flow.

| Agent | Plays | May call (loopback only) | Talks to |
|---|---|---|---|
| Griddy Grid Desk (`fetch_agents/grid_desk.py`) | the utility; the only agent a judge chats with | `GET /api/state` | the judge, Facility, Verifier |
| Griddy Facility (`fetch_agents/facility.py`) | this Mac | `POST /request` with `"source": "fetch"`, `GET /api/approvals`; a second client for the operator's chat answer: `POST /api/approvals/{id}/reply` | Grid Desk only |
| Griddy Verifier (`fetch_agents/verifier.py`) | an independent meter check | none: it reads `runs/<id>/timeline.jsonl` from disk | Grid Desk only |

Any other call raises NotAllowed in the client before a request is built. Facility and Verifier drop any message that
is not from Grid Desk's address. Each agent rate-limits each sender.

## The flow a judge sees
1. Ask Grid Desk "How stressed is the CAISO grid right now?": the live price, carbon, fuel mix and alerts with the
   feed's age (GET /api/state).
2. Ask "I need 30% off for 20 minutes". Grid Desk reads it by rule (percent or watts, and a duration; one question
   back if a part is missing) and sends a CurtailmentRequest to Facility.
3. Facility hands it to Griddy's own intake, which stages it as a pending operator approval and does not apply it.
   Facility answers with the Offer: the intake's readback, the target watts, and what the solver's preview does in
   that slot. Grid Desk relays it: "Waiting for the facility's operator."
4. The operator answers, in the same chat (Fetch asks for the whole flow inside ASI:One) or on the operator page:
   "yes", or "no, training has a deadline tonight". In the chat, Grid Desk passes a message that starts with yes or
   no to Facility word for word, and Facility hands it to the same rule-based reader the operator page uses; anything
   else gets "Not understood". Facility sees the answer and sends the Outcome. A refusal ends the deal and nothing
   is applied.
5. On an approval the cap applies and the watts drop. A minute later Grid Desk asks Verifier. Verifier reads the run's
   measured power rows and computes, with the reporter's rules (`make verify`): the 60-s baseline before the cap, the
   mean since, the share of samples at or under the cap, and the time to compliance (the 10-s mean at or under it).
   Grid Desk relays the verdict with the run id and the file, so anyone can recompute it.

If the runtime is down, every agent says so and gives no number. A request to do anything else (pause a job, switch
the grid, approve, break a part) is refused.

## Set it up (once, about 5 minutes, on the demo Mac)
1. Three seeds, one per agent. Each fixes that agent's address. Written straight into `.env`, never shown:
   ```bash
   for r in GRID_DESK FACILITY VERIFIER; do printf 'FETCH_%s_SEED=%s\n' "$r" "$(openssl rand -hex 32)" >> .env; done
   ```
   The agents find each other's addresses from these seeds (or from `FETCH_<ROLE>_ADDRESS`, if one runs elsewhere).
2. The Agentverse key: the same `AGENTVERSE_API_KEY` as the read-only agent (docs/fetch-agent.md, step 2), put in
   `.env` by the human. Never commit or paste it.
3. With `make demo` up, run `make fetch-three`. Each agent prints its address and registers a mailbox on Agentverse.
4. On agentverse.ai open Agents, then Griddy Grid Desk, then Chat with Agent: that opens ASI:One.

Only run it against a runtime that stages fetch requests (machine 1's `POST /request` change). Facility checks every
response for `staged: true` and an approval id; if one is missing, it stops taking requests and says why, because a
runtime without the change would have applied the cut without asking the operator.

## Tested (`tests/test_fetch_three.py`, fakes only in tests)
- The messages round-trip; the allowlists are exact, and no write route is ever built.
- A stranger's message is dropped by Facility, Verifier and Grid Desk.
- Facility stages, offers, waits and reports, and never calls an apply route; a refusal applies nothing; a runtime
  that does not stage stops it.
- Grid Desk reads cuts by rule, asks one question when unclear, refuses everything else, ignores instructions inside
  a message, and quotes only the runtime and the Verifier.
- Verifier matches `agent/reporter.py` exactly on every committed evidence run (the run of record reads 14.34 W, 93 %
  under the cap, compliant in 12 s); no power rows means "not measured" and no number.
- Rate limits hold; the read-only agent (agent/channels/fetch_agent.py) is unchanged.
