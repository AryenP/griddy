# Griddy

Built at Cal Hacks 13 for the Microsoft Challenge. The project started out as "Brownout", which is why that name
still shows up in the code and the repository.

When the power grid runs short, the usual plan for AI data centers is to switch to diesel generators. Griddy is a
different answer.

Griddy watches the live grid (prices, the day-ahead forecast, the fuel mix and emergency alerts) and plans every AI
job on the machine for the next 24 hours. When the grid needs power back, it pauses or slows the work that can wait,
keeps the services people are using running, and asks a job's owner before it pushes back their deadline. Then it
shows what it did using the power the machine actually drew.

Microsoft judges: [docs/microsoft.md](docs/microsoft.md) maps each judging criterion, and each of Microsoft's six
Responsible AI principles, to the code that covers it.

## Every number is real

Prices and power readings are live or measured, and the screen shows where each number came from and how old it is.
The grid emergencies you can replay use the grid operators' own records (U.S. EIA Form EIA-930), and every alert and
impact figure is cited to a page of the official report. Anything that isn't measured says so: a failure you make up
is labelled "what-if", and grid-scale figures are labelled "estimate". `make verify` recomputes every published
number from the raw logs.

## What it could mean at grid scale

This is an estimate, and the app labels it as one.

Winter Storm Uri, in February 2021, left more than 4.5 million people in Texas without power and at least 210 dead,
and forced 20,000 MW of load to be shed (FERC-NERC report, PDF pp. 10 and 15).

We replayed Uri through Griddy on 24 October, using the stored copy of the EIA data because the public API key had hit
its rate limit. When ERCOT declared its highest emergency level, EEA 3, this Mac dropped from 28.2 W to 10.9 W,
measured, a 61 % cut.

We only count the 40 % cut the grid actually asked for. Applied to ERCOT's large loads, up to 4.1 GW (the sum of each
load's own monthly peak, so an upper bound), that frees up to 1,653 MW. That is about 8 % of what Uri shed, or about
372,000 people kept on, using the storm's own ratio of people out per MW shed (DECISIONS 18:38). At the 25 % cut
Emerald AI has shown on a real GPU cluster in Phoenix, held for three hours (see RESEARCH.md), the same math gives
about 1,000 MW and about 230,000 people.

<details><summary>Terms used in this README</summary>

- **ISO**: the grid operator, such as CAISO in California or ERCOT in Texas.
- **EEA 3**: a grid operator's highest emergency level, when rotating outages begin.
- **Cap**: the most power the utility asks a site to draw for a while.
- **Slot**: 15 minutes of the 24-hour plan.
- **Time to compliance**: seconds from the start of a cap until the 10-second average power is at or under it.
- **CP-SAT**: the constraint solver in Google OR-Tools.
- **EIA-930**: the U.S. Energy Information Administration's hourly record of each grid's demand, forecast and fuel mix.
- **OpenADR 3.1**: the standard utilities use to send demand-response events.
- **SoC power**: the chip's CPU, GPU and Neural Engine watts, as macOS powermetrics reports them.
- **DECISIONS hh:mm**: an entry in [DECISIONS.md](DECISIONS.md), our timestamped log of every decision made during
  the build.
</details>

## Compared with the usual options

When a utility asks a data center to cut back, the choices today are blunt: start the backup generators, ignore the
request, or switch off everything that can be switched off. Griddy works job by job, in 15-minute slots.

| | Backup diesel | Ignore the call | Pause everything | Griddy |
|---|:---:|:---:|:---:|:---:|
| Stays under the utility's cap | ✅ | ❌ | ✅ | ✅ within seconds |
| No on-site burning of fuel | ❌ | ✅ | ✅ | ✅ |
| Services people are using stay up | ✅ | ✅ | ⚠️ only if someone spares them by hand | ✅ never paused |
| Delayed work still meets its deadline | ✅ | ✅ | ⚠️ nothing is rescheduled | ✅ re-planned, or the owner is asked first |
| Flexible work moves to cheaper hours every day | ❌ | ❌ | ❌ | ✅ live prices (carbon uses today's live mix, held flat) |
| Owners are asked before a deadline slips | n/a | n/a | ❌ | ✅ in plain words |
| Says so when the cap can't be met | n/a | n/a | ❌ | ✅ the solver's own shortfall |
| Proves it with measured power | n/a | ❌ | ❌ | ✅ every second, timestamped |

## Results so far

We ran the same jobs on the same live grid with the same request (a cap 30 % below the measured baseline, starting
2 minutes in and lasting 5 minutes, with training due in 2 hours), once with Griddy off and once with it on. Power was
measured by macOS powermetrics on one M2 Pro, and every figure comes from the runs' own logs.

| Run (code) | Mode | Average power during the cap | Time at or under the cap | Time to compliance | Training deadline |
|---|---|:---:|:---:|:---:|:---:|
| [02:28](docs/evidence/compare-20261024-022026-vs-20261024-021247-baseline.md) (e90eef1) | Griddy off | 18.32 W | 0 % | never | met, projected from measured steps ✅ |
| | Griddy on | 0.68 W | 99 % | 5 s | met in the solver's plan ✅ |
| [03:10](docs/evidence/compare-20261024-025349-vs-20261024-024609-baseline.md) (13f6b3b) | Griddy off | 21.18 W | 0 % | never | met, projected from measured steps ✅ |
| | Griddy on | 1.64 W | 99 % | 7 s | met in the solver's plan ✅ |

We also compared it with pausing everything, done properly. One run each, same request (the 09:15 run of record,
DECISIONS 09:46; 315 to 327 seconds from each cap start, cap 15.10 W):

| Approach | Average power during the cap | Time at or under the cap | Time to compliance | Training steps during the cap |
|---|:---:|:---:|:---:|:---:|
| [Ignore the call](docs/evidence/compare-20261024-093434-vs-20261024-091909-baseline.md) | 20.85 W | 0 % | never | 5899 |
| [Pause everything](docs/evidence/compare-20261024-093434-vs-20261024-092650-pause_all.md) | 0.80 W | 99 % | 4 s | 19 |
| Griddy | 14.34 W | 93 % | 12 s | 1575 (315 s; 1625 over ignore's 327 s) |

Griddy kept training running on the CPU under the cap. That is about 83 times as much work as pausing everything,
and instead of breaking the cap it asked the owner about the roughly 19-minute delay.

These are short runs on a single laptop. At laptop wattage the dollar savings are fractions of a cent; what matters is
that it gets under the cap in seconds while the work keeps going. The live run of a request, an owner refusing and
the operator approving is in [docs/evidence/demo-flow-live-20261024.md](docs/evidence/demo-flow-live-20261024.md).
The responsible-design evals are in [docs/evidence/evals-live-20261024-2033.md](docs/evidence/evals-live-20261024-2033.md):
135 of 138 passed live on Saturday at 20:33, all 19 prompt-injection attempts were rejected, and the fault reader
scored 14 of 14. The first live run, at 02:33, passed 86 of 90.

## Who decides what

- **The utility** asks, in plain words or as an OpenADR 3.1 event. Griddy reads the request back with real numbers
  and turns it into a cap. It is never treated as an instruction to the system.
- **The solver** (CP-SAT) decides when each job runs, on which device and how hard, from live prices, the fuel mix,
  caps, deadlines and measured watts. Given the same inputs it always makes the same plan.
- **Job owners** approve or refuse a deadline slip in their own words. A refusal makes the deadline fixed.
- **The operator** decides when the cap and a refused deadline conflict. Until they approve going over the cap, the
  plan keeps to it.
- **The controller** is the only code that can change how a job runs. The AI explains and negotiates; it has no way
  to change anything.
- **The off switch** is "Dispatcher off" on the dashboard: every job then runs as if Griddy weren't there.

## Try it without a Mac

Works on Windows, Linux or macOS, with no network and no keys.

```
python -m pip install uv                      # python3 on macOS and Linux; "python -m uv" works even when uv is not on PATH
python -m uv sync --extra dev
python -m uv run python scripts/verify.py     # = make verify: recomputes every published measured number from the raw logs
python -m uv run pytest -q                    # the full test suite
python -m uv run python -m evals --no-write   # the AI-layer evals, offline, printed only (add --live with an ANTHROPIC_API_KEY)
```

## Run it on an Apple-silicon Mac

```bash
make setup            # uv environment and dependencies (for Azure: uv pip install -e '.[azure]')
cp .env.example .env  # add your keys; never commit .env. PJM also needs PJM_API_KEY (CAISO and ERCOT need none)
ollama pull qwen3:4b-instruct   # the chat model (plain qwen3:4b always "thinks" and leaks its reasoning)
sudo -v               # powermetrics needs sudo (or install the passwordless rule in team/README.md)
make probe            # what this Mac supports: powermetrics, MPS, Ollama, a live CAISO price
make calibrate        # measure idle power and each job's power with powermetrics
make demo             # grid feeds, meter, workloads, dispatcher and dashboard on :8080
make baseline         # the same jobs with the dispatcher off, for 10 minutes, for comparison
make evidence         # unattended: calibrate, then a dispatcher-off run and a dispatched run with the same cap, and compare
make evidence3        # unattended (~30 min): calibrate, then ignore the call, pause everything and Griddy, and compare
make evidence-chat    # unattended (~12 min): calibrate chat at 1, 2 and 4 streams, then a capped run with 2 chat streams
make evidence-chat-judge  # unattended (~8 min): one person chatting during the cap, 15 s to read each reply
make report RUN=<id>  # reports/<id>.md and a power chart, from that run's log only (default: the latest run)
make compare          # newest dispatched run vs newest baseline run (or DISPATCHED=<id> BASELINE=<id>)
make fetch-three      # the three Fetch.ai agents for the running app (see below)
make test
```

Azure (Application Insights for the decision trace): run `azd auth login` and `azd provision`, then copy
`APPLICATIONINSIGHTS_CONNECTION_STRING` from `azd env get-values` into `.env`. Without the `[azure]` extra or the
connection string, the trace stays in memory and is readable at `/api/trace`.

## How it fits together

Grid data comes in, the CP-SAT solver makes a plan, the controller carries it out on the Mac, powermetrics measures
the result, and everything is written to a log that the dashboard, reports and comparisons read from. The AI handles
messy requests, talks to job owners and writes the explanations, but it never changes how a job runs.

You can also replay a real grid emergency: Winter Storm Uri (Texas, 2021), California's rotating outages (2020) or
California's record heat wave (2022). When you press play, Griddy fetches the grid operator's hourly demand, forecast
and fuel mix from the U.S. EIA and only sees each hour once it has ended. tests/test_replay.py deletes every later
hour and checks that nothing changes, so Griddy can't see ahead and isn't trained on any event. Each alert reaches the
real dispatcher at the moment it was issued, and the page compares this Mac's measured response with what the event
cost (replay/engine.py, replay/eia.py, config/events.yaml).

You can also break any part of the grid, by clicking it or by describing the failure in your own words. The failure is
labelled "what-if", its size is the grid's real output at that moment, and the same live dispatcher responds
(replay/whatif.py, agent/faults.py). Clicking the city opens a map of one real square, drawn 1:1 from OpenStreetMap:
Houston's Texas Medical Center for ERCOT, and for CAISO, San Francisco from SoMa to Mission Bay, where Cal Hacks is
held. The San Francisco square has a real data center building (365 Main St; this Mac stands in for it, and the
building itself plays no part), PG&E's Embarcadero substation and UCSF Mission Bay. Homes go dark in line with the
grid's real shortfall, and the power Griddy frees turns blocks back on. Which blocks, and how the feeders are routed,
is illustrative, and the page says so. California's live price is PG&E's default load price (DLAP_PGAE), the one San
Francisco pays.

![How Griddy fits together](docs/judging/architecture.svg)

More: [docs/architecture.md](docs/architecture.md). Interfaces: [SPEC.md](SPEC.md). API contract:
[HANDOFF.md](HANDOFF.md). Every decision made during the build: [DECISIONS.md](DECISIONS.md).

## Fetch.ai agents

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Three agents run a power-cut request from start to finish inside one ASI:One chat. All three are registered on
Agentverse with a mailbox, and Grid Desk speaks the Agent Chat Protocol.

| Agent | Address | What it does |
|---|---|---|
| **Griddy Grid Desk** | `agent1qt7cas9mg84lylw7eaw938hzzyqcj9zxddwv5z6pz8lp70kzj6p62geu5t9` | The utility. The one you chat with: live grid numbers with their source, and cut requests |
| **Griddy Facility** | `agent1qdds386n744y2jtv0nyaaj55fah4a73am6dgq765t9jd09u9mjltunydvdm` | This Mac. Stages the cut in Griddy's own intake and offers what its solver can do. Never applies it on its own |
| **Griddy Verifier** | `agent1qtn9qm94g68we4fqp9r5sjdvda49c6sddtrznymg24fcc4p6nkqajfwnmcx` | The independent check. Reads the measured watts from the run's log, with the same rules as `make verify` |

Try it: on [agentverse.ai](https://agentverse.ai) open **Griddy Grid Desk**, then **Chat with Agent**, and send:

1. `How stressed is the CAISO grid right now?` It answers with live numbers and where they came from.
2. `I need 30% off for 20 minutes`. Facility replies with its offer: the watts, and which jobs pause.
3. `yes` to approve, or `no, training has a deadline tonight` to refuse. You answer as the facility's operator. Only a
   plain yes, or no with a reason, is accepted, and nothing changes until you answer. The operator page works too.
4. About a minute after a yes, Verifier's report arrives: mean watts, share of time under the cap, time to
   compliance, and the run id, so anyone can recompute it.

No AI model makes any decision in this flow. To run the agents yourself you need `make demo` running, an Agentverse
API key and three seeds in `.env` (see `.env.example`), then `make fetch-three`. Setup and the rules each agent follows
are in [docs/judging/fetch-three-agents.md](docs/judging/fetch-three-agents.md).

## What each sponsor tool does here

| Tool | What it's used for, and what happens without it |
|---|---|
| Claude Sonnet 5.5 through the Anthropic SDK (`agent/llm.py`). A Microsoft Agent Framework + Foundry path sits behind the same interface; it is built but not yet run against a Foundry deployment | Reads free-text requests and owner replies, and writes the explanations. Without it, the plain forms ("30% for 20 minutes", "yes", "no, <reason>") and OpenADR JSON are still read by rules, explanations fall back to the solver's facts word for word, and the app shows "agent offline" and keeps running |
| OpenTelemetry (`telemetry/`), readable at `/api/trace`. Azure Application Insights is set up (`infra/`, `azure.yaml`) but not connected in this build | The audit log of who decided what, when and why |
| Google OR-Tools CP-SAT (`dispatcher/`) | The plan itself, and the answer to "how much can we still deliver?" after a refusal |
| gridstatus for CAISO and ERCOT, and PJM with `PJM_API_KEY` (`grid/`) | Live prices, fuel mix and alerts. Without them the plan has nothing to work from |
| macOS powermetrics (`meter/`) | Every watt in the reports and comparisons |
| Fetch.ai uAgents (`fetch_agents/`) | Running a request from ASI:One between the utility, the facility and an independent check |

## How results are measured

- `agent/reporter.py` (`make report`, `/api/report`) works out:
  - the baseline: the average measured power in the 60 seconds before the cap starts;
  - the average during the cap, and the percentage reduction;
  - time to compliance: the first moment the 10-second average is at or under the cap;
  - energy, cost at the live price for each second, and carbon at the live fuel mix;
  - deadlines, and approvals (who was asked, who answered and what they said);
  - chat's time to first token (95th percentile, against the 1-second target in `policy.sla.chat_ttft_p95_s`)
    before and during the cap, with total reply time alongside;
  - any shortfalls.
- `scripts/compare.py` (`make compare`, `/api/compare`) compares a dispatched run with a dispatcher-off run over the
  same length of time.
- Emission factors are IPCC AR5 lifecycle medians (the CARB default for imports), cited per fuel in
  `config/isos.yaml`.

## Limits

Everything here ran on one MacBook (Apple M2 Pro). Power is the chip's CPU, GPU and Neural Engine draw as
powermetrics reports it, from about 0.5 W idle to about 26 W for the busiest job (DECISIONS 02:28, 03:10), not a
wall-socket reading. The grid feeds, the solver, the approvals and the audit trail would work the same way for a
50 MW data center; the difference is that the controls there are cluster schedulers and power caps.

## Team

Four machines, one repo: [team/README.md](team/README.md).
