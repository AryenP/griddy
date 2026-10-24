# Brownout — verified facts for the build (updated 23 Oct 2026, 8:55 PM: dispatcher on one Mac)

(S) = secondary source or unverified; test on the machine before relying on it.

## Live grid data (VERIFIED from the venue network, Fri 8:50 PM, no API key)
- `pip install gridstatus` (0.37.0). `gridstatus.CAISO().get_lmp(date="today", market="REAL_TIME_5_MIN", locations=["TH_SP15_GEN-APND","TH_NP15_GEN-APND"])` → 5-min rows with `Interval Start`, `LMP`, `Energy`, `Congestion`, `Loss`, `GHG`. At 8:50 PM: NP15 $58.10, SP15 $52.62 per MWh. Markets: REAL_TIME_5_MIN, REAL_TIME_15_MIN, DAY_AHEAD_HOURLY.
- `CAISO().get_load_forecast("today")` → 24 hourly rows `Load Forecast` (DAM). `CAISO().get_fuel_mix("today")` → 5-min MW by Solar, Wind, Geothermal, Biomass, Biogas, Small Hydro, Coal, Nuclear, Natural Gas, Large Hydro, Batteries, Imports, Other.
- `gridstatus.Ercot().get_real_time_system_conditions()` → Current Frequency, Actual System Demand, Total System Capacity, wind, PV, inertia. ERCOT prices: `get_spp(date, market=...)`, markets REAL_TIME_15_MIN / DAY_AHEAD_HOURLY. PJM: `get_lmp(date, market, locations="hubs")`, markets REAL_TIME_5_MIN / REAL_TIME_HOURLY / DAY_AHEAD_HOURLY.
- CAISO OASIS calls take 1–5 s and the library sleeps between requests; poll on a background task, never in the request path.

## This Mac (Apple silicon) — verify with `make probe`
- Power: `sudo powermetrics --samplers cpu_power,gpu_power -i 1000` prints `CPU Power`, `GPU Power`, `ANE Power`, `Combined Power` in mW each sample. Independent of our code (OS-reported SoC power), not a wall meter; say "SoC power, measured by macOS". Needs sudo; run `sudo -v` first. (S: field names vary slightly across macOS versions; probe prints what exists.)
- LLM serving: Ollama on Apple silicon (Metal). `OLLAMA_NUM_PARALLEL` is fixed at server start, so concurrency is controlled by our proxy semaphore. A 4B–8B model keeps replies under ~2 s p95 on an M-series laptop with 1–2 concurrent users (S; measure and set the SLA from the measurement).
- Training: PyTorch MPS (`torch.backends.mps.is_available()`); small model; `torch.save` every N steps; cooperative pause at step boundaries; moving a job between GPU and CPU = restart from checkpoint on the other device. Thread count via `torch.set_num_threads` for CPU jobs.
- Expected swing: idle ~3–8 W SoC; a busy GPU job 15–30 W; combined under load 30–45 W on a 14-inch Pro-class laptop (S). Calibrate; never type watts into config.
- Knobs available: run/pause/resume, concurrency, threads, device placement, model size. No clock lock, no power limit on macOS.

## Optimizer
- OR-Tools CP-SAT (`pip install ortools`): 3 jobs × 96 slots × small concurrency domains solves in well under 1 s; set `max_time_in_seconds=2`. On infeasibility, solve a second model with slack variables (deadline slack, cap slack) minimised to get the minimal relaxation for the negotiator.

## The bold claim (verified)
- Winter Storm Fern, late Jan 2026: 1M+ customers out, mostly Southeast. The Energy Secretary authorised PJM, ERCOT and Duke to order data centers and other large users onto backup generators, citing "35 gigawatts" of diesel. No reported request to shed compute. Source: Fortune, 4 Feb 2026, "Over a million people are losing power during a freezing snowstorm while data centers nearby guzzle electricity". Pitch line: "When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative."

## The request format: OpenADR 3.x
- REST/JSON. VTN (utility/aggregator server) exposes Program, Event, Report, Subscription, VEN, Resource; VENs poll or subscribe. Spec (OpenAPI YAML) free at openadr.org; 3.1 is not backward compatible with 3.0.
- Open-source VTN to run locally: **OpenLEADR-rs** (github.com/OpenLEADR/openleadr-rs, Rust, 3.1, Docker Compose with Postgres on :3000, 166/168 Alliance tests). Go alternative: otfabric/go-openadr.
- Event payload types include SIMPLE (levels 0–3), PRICE, DISPATCH_SETPOINT, IMPORT_CAPACITY_LIMIT, EXPORT_CAPACITY_LIMIT, ALERT_GRID_EMERGENCY, ALERT_FLEX_ALERT.
- Minimal event (adapted from an OpenLEADR fixture; the IMPORT_CAPACITY_LIMIT units/semantics and `targets` are unverified, check the 3.1 definitions):
```json
{"objectType":"EVENT","programID":"dc-curtailment-prog-1","eventName":"heat-wave curtailment",
 "priority":0,"targets":[{"type":"RESOURCE_NAME","values":["campus-A"]}],
 "payloadDescriptors":[{"objectType":"EVENT_PAYLOAD_DESCRIPTOR","payloadType":"IMPORT_CAPACITY_LIMIT","units":"KW"}],
 "intervalPeriod":{"start":"2026-10-25T18:00:00Z","duration":"PT10M","randomizeStart":"PT0S"},
 "intervals":[{"id":0,"payloads":[{"type":"IMPORT_CAPACITY_LIMIT","values":[0.07]}]}]}
```

## Why a utility can order this (cite these)
- **Texas PUCT Docket 59220 (24 Jul 2026):** co-located data centers must fully curtail on ERCOT instruction; ≥60 min notice "when practicable"; 30-minute full-curtail capability, uncompensated. Texas SB6 (2025): loads ≥75 MW must be remotely disconnectable in firm load shed.
- **PJM Board (16 Jan 2026):** new large loads ≥50 MW not paired with generation ("connect and manage") are curtailed before pre-emergency DR; load-shed rules due end-2026.
- **FERC show-cause orders (18 Jun 2026):** RTOs must consider non-firm/interim service for flexible large loads ≥50 MW. **DOE §403 directive (23 Oct 2025):** loads that accept curtailment get expedited interconnection studies.
- **EPRI DCFlex:** 10–30% peak-reduction potential (EPRI via Reuters, 8 Oct 2026).

## Prior art (own it before the judge raises it)
- **Emerald AI:** 25% GPU-cluster reduction for 3 h, Phoenix, with Oracle Cloud, NVIDIA, EPRI, SRP; results 1 Jul 2025; paper "Turning AI Data Centers into Grid-Interactive Assets" (arXiv); $24.5M seed; 96 MW Virginia site planned. No public code.
- **Google:** demand-response agreements with Indiana Michigan Power and TVA for ML workloads (4 Aug 2025); earlier OPPD pilot cut ML load in three 2024 grid events.
- **Sep 2026:** Google, NVIDIA, Emerald launched an "AI Energy Management Alliance"; OpenAI agreed to shed up to 1 GW of a 3.2 GW Georgia site (Reuters, 8 Oct 2026).
- **Microsoft:** Jan 2026 "Community-First AI Infrastructure" pledge (pay full power costs, fund grid upgrades); no public flexibility/curtailment statement found (S). Pitch line: "Microsoft has committed to being a good grid citizen; this is the tool that proves it."
- **How compliance is verified in real programs (S):** revenue-grade interval meter data (5–15 min), performance vs a baseline ("10-of-10" average of recent similar days, often same-day adjusted), real-time telemetry in ERCOT-style programs, penalties on shortfall. Model it: pre-event baseline window → event-window mean → % reduction → time-to-compliance.

## Microsoft stack (what is realistic in 36 h)
- **Microsoft Agent Framework:** `pip install agent-framework` (1.12.x, Jul 2026); `from agent_framework import Agent`; `agent_framework.openai.OpenAIChatClient` works with any OpenAI-compatible endpoint; `agent_framework.foundry.FoundryChatClient(project_endpoint=..., model=..., credential=DefaultAzureCredential())` for Foundry. Hosting: `agent-framework-foundry-hosting` (prerelease), `ResponsesHostServer(agent).run()`, `azd ext install azure.ai.agents` → `azd ai agent init/run`, `azd provision && azd deploy` (also provisions Application Insights). Hosted MCP tools: `client.get_mcp_tool(name, url, approval_mode="always_require", allowed_tools=[...])` — maps to human approval + least privilege.
- **Foundry Agent Service:** GA 24 Sep 2026; Routines (schedule/timer/GitHub/Teams triggers, public preview, run published agents), Tool Search, agent-to-agent delegation; GPT-6 Astra, Luna, 6.1 Sol and Claude Opus 5.5 on Foundry. Astra access may need a request; use a 5.x/4o deployment under student quota.
- **Teams two-way messaging:** needs tenant admin consent (Graph `ChatMessage.Send`) or a Bot in a tenant; M365 Developer sandbox often "not qualified" in 2026. **Use Slack or the web owner console; say "Teams via the Microsoft 365 Agents SDK in production."**
- **Application Insights / OpenTelemetry:** realistic, highest value; traces visible in the Foundry portal.
- **Entra Agent ID:** not self-serve for a student; say "per-agent Entra Agent ID in production".
- **Azure AI Content Safety `shieldPrompt`:** ~1 hour; run on inbound free text before the planner.
- **Quote in the pitch:** Microsoft Security Blog, "Least privilege for AI agents: identity, access, and tool binding" (16 Jul 2026): dedicated agent identities, task-scoped time-limited access, tool allowlists, step-up human approval for high-impact actions, audit logs. Also Foundry's Agent Control Specification (deterministic controls at tool checkpoints) and open-source ASSERT (policies → executable evals), Build 2026.

## Prize-track facts (Devpost, 23 Oct)
- Microsoft 1st: $3,800 cash + Surface per member + FDE tech talk + mentorship; 2nd: talk + mentorship.
- Overall: Most Technically Advanced Hack (NuPhy), Best Planet-First (parks pass), Best Solo Hack (AirPods Pro 3), Hacker's Choice.
- SpaceXSI: must be built with Cursor; bonus for Grok Bot in planning; $400 + Cursor keyboard. Only if Cursor is used anyway.
- Hyphenate requires a demo video. Cartesia/Bright Data/Creao/Mana/Fetch have hard requirements that this project does not meet; do not opt in.

## Sources
Spheron DGX Spark thermal/power (2026); ai-muninn DGX Spark 30 W mode; NVIDIA developer forums (GB10 60 W cap thread, 721 MHz thread); vLLM blog "vLLM on DGX Spark" (1 Jun 2026); CRIUgpu arXiv 2502.16631; ml-energy/zeus; OpenLEADR-rs GitHub; openadr.org 3.0/3.1 spec; Foley (DOE §403); Akin (FERC show-cause); PJM Board letter 16 Jan 2026; Perkins Coie (SB6); White & Case (PUCT 59220); Reuters/The Star 8 Oct 2026 (DCFlex, alliance, OpenAI 1 GW); APPA and NVIDIA blog (Emerald/SRP); Google blog 4 Aug 2025; Microsoft On the Issues 13 Jan 2026; PyPI agent-framework; Microsoft Learn hosting/hosted-MCP docs; Message Center AZ563536 (Routines); Azure blog GPT-6 Astra on Foundry (3 Sep 2026); Microsoft Security Blog 16 Jul 2026; Devpost cal-hacks-13-0.
