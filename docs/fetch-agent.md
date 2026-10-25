# Griddy on ASI:One (Fetch.ai)

A judge talks to Griddy from ASI:One. The agent (`agent/channels/fetch_agent.py`) is a uAgents agent that speaks
the Agent Chat Protocol and is registered on Agentverse in mailbox mode: it polls Agentverse for messages, so
it works behind the venue NAT with no open port. It answers from the runtime on this Mac and can only read.

| It may call (loopback only) | For |
|---|---|
| `GET /api/state` | live grid, measured watts, the plan, the last replay |
| `GET /api/explain` | the current schedule's explanation |
| `GET /api/replay/events` | the three real grid emergencies, cited |
| `POST /api/ask` | "why" questions, answered from live state (api/access.py trusts loopback) |

Any other call raises `ReadOnly` in the client before a request is built. Messages that ask it to act (pause,
cap, switch, replay, approve, break...) get a refusal and never reach the runtime. If the runtime is down, it says
so and gives no number. Every number in a reply comes from those routes, with the route and the runtime's source.

## Set it up (Aryen, once, about 5 minutes)

1. Seed. It fixes the agent's address, so ASI:One finds the same agent every time. This writes it straight
   into `.env` without showing it:
   ```bash
   printf 'FETCH_AGENT_SEED=%s\n' "$(openssl rand -hex 32)" >> .env
   ```
   Keep it. A new seed is a new agent with a new address.
2. Agentverse key. Sign in at https://agentverse.ai with your own account, open the profile menu, then
   API Keys, and create a key. Put it in `.env` yourself as `AGENTVERSE_API_KEY=...`. Never commit or paste it.
3. Run. With `make demo` up in another terminal:
   ```bash
   make fetch-agent
   ```
   The first run builds the agent's own environment (about 50 packages, cached after that). Expect:
   - `Runtime answering at http://127.0.0.1:8080; this agent may only call: ...`
   - `Griddy agent address: agent1q...` (public; copy it for step 5)
   - `Registered on Agentverse with a mailbox: find Griddy in ASI:One`
4. Find it in ASI:One. On https://agentverse.ai open Agents: Griddy is listed as a mailbox agent. Open it,
   then Chat with Agent: that opens ASI:One with Griddy. Ask one of the starter prompts:
   - How stressed is the CAISO grid right now?
   - What is the Mac drawing right now?
   - Why is training paused?
   - What happened in Winter Storm Uri, and what would Griddy have freed?

   ASI:One can also pick Griddy by itself for grid questions once Agentverse has indexed its profile, which
   can take a while. For the demo, use the Chat with Agent button.
5. README (prize rule). Fetch asks for the agent's name and address in the README, with their badges. Add
   this to `README.md` with the address from step 3:
   ```markdown
   ## Fetch.ai agent
   ![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
   ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

   **Griddy** (read-only, Chat Protocol, mailbox): `agent1q...`. Ask it in ASI:One; see docs/fetch-agent.md.
   ```
   The agent's Agentverse profile already carries the badges, a description and the starter prompts.

Keep `make fetch-agent` running for as long as ASI:One should reach it. Ctrl+C stops it, and uagents marks it
inactive.

## What a judge sees

- Grid: price for the current interval, the prices ahead (day-ahead curve), carbon, the three largest fuels,
  the load-forecast peak, ISO alerts, caps on this Mac, the feed's age and the OASIS source URL. If the judge
  names the other ISO, it says which one Griddy is watching and gives that ISO's live demand from the snapshot.
- Power: combined, CPU, GPU and ANE watts measured by powermetrics and how old the sample is, plus the
  plan's expected watts, marked planned and not measured.
- Why: the runtime's answer from `POST /api/ask`, the facts its numbers come from, and the live plan, so a
  wrong premise ("why is training paused?" while it runs) shows.
- Events: the cited impacts and Brownout's flag from the replay catalog. "What would Griddy have freed"
  quotes the last replay's measured cut and its scaled estimate (labelled ESTIMATE). If that event has not been
  replayed since the runtime started, it says so instead of giving a number. The agent cannot start a replay.

## Safety

- Read-only by construction. `Runtime.call` checks an exact `(method, path)` allowlist, and redirects are not
  followed. `tests/test_fetch_agent.py` tries every write route in HANDOFF.md (and `/api/whatif`) and checks
  that no question reaches anything else.
- Loopback only. The client refuses a non-loopback runtime URL. uagents would serve its own local routes,
  the Inspector's `/connect` among them, on every interface. The agent pins them to `127.0.0.1` (port
  `FETCH_AGENT_PORT`, default 8001), because mailbox mode needs no inbound connection.
- Question limit. `/api/ask` allows 10 questions a minute per device, and ASI:One questions come from this
  Mac. Past the limit, the agent answers with `GET /api/explain` and says why. Each question is logged in the
  run's timeline as a `note` with `ask`.
- Secrets. `AGENTVERSE_API_KEY` and `FETCH_AGENT_SEED` live in `.env` only (`.env.example` has them empty).
  The agent never prints or logs them. It logs a sender's first characters and the first 120 characters of
  each question.

## Why its own environment

uagents 0.26.1 pulls in cosmpy, which needs protobuf < 6. The runtime's OR-Tools uses protobuf 6, so installing
uagents into the demo's venv would downgrade protobuf under the solver. `make fetch-agent` runs
`uv run --no-project` with pinned `--with` packages instead. The agent imports nothing from the runtime: it
reaches it over HTTP only.

## If it fails

| You see | Do |
|---|---|
| `FETCH_AGENT_SEED is empty` | step 1 |
| `AGENTVERSE_API_KEY is empty` | step 2, then restart. Or open the "Agent inspector" link it prints, then Connect, then Mailbox |
| `Agentverse registration failed: ...401...` | the key is wrong or expired: make a new one (step 2) |
| `...409...` | this address belongs to another Agentverse account: use that account's key, or a new seed |
| `could not reach Agentverse` | the network: check the venue Wi-Fi, then restart |
| `Agent mailbox not found` warnings | registration did not run or failed: read the line above it |
| replies say the runtime is not answering | start `make demo` first; the agent needs no restart |
