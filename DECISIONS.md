# Decisions log

Append-only. Date, decision, why. Claude Code adds entries when it deviates from SPEC.md or learns something about the hardware.

- 2026-10-23 20:35 — Project: Brownout, grid-responsive compute agent, framed as "AI facility under a utility curtailment order". Chosen over Countersign (AP fraud), Aftercare (clinical after-the-note), PayCheck (pay-stub audit) because it fits the builder's GPU/inference strengths, has a physical judge-controlled demo, and sits on 2026 regulation (PUCT 59220, PJM 50 MW). See .court/VERDICT.md.
- 2026-10-23 20:35 — Court verdict on the base idea: GUILTY 4–2 as described. Six conditions adopted: (1) operator/FDE quote on slide one, (2) one Microsoft-native thing running live (Agent Framework + App Insights trace on screen), (3) DR-style baseline + time-to-compliance as the headline metric, (4) lamp step only if rehearsed under 5 s, (5) give the LLM messy inputs and free-text negotiation, (6) stability over features with sim fallback.
- 2026-10-23 20:35 — Space variant (EO flood jobs as tenants): jury 6–0 for base framing. Adopted as a conditional: tenants become Sen1Floods11 flood-segmentation jobs only if a pretrained checkpoint + staged tiles render live on the box by Sat 1 PM with under 2 h of work; otherwise generic training + embedding tenants. SpaceXSI track ignored unless Cursor is used anyway.
- 2026-10-23 20:35 — Knob on GB10 is clock locking (`-lgc`), not power limit; confirm with scripts/probe_hardware.sh on the box.
- 2026-10-23 20:35 — Owner channel: web console on the judge's phone by default; Slack if time; Teams documented as production path (needs tenant admin).
- 2026-10-23 20:35 — Agent model: Claude by default behind agent/llm.py; Microsoft Agent Framework + Foundry when Azure credits are live. Both must work.
- 2026-10-23 20:30 — Wrapper rule (from sponsor criteria: Factory, Cartesia, CRS, Notability): remove the component and something must break, or it is not integrated and not opted in. LLM must own messy intake, free-text negotiation and shortfall prose. App Insights trace = the audit log on screen. Fetch only as the utility-side agent negotiating across ≥2 facility agents (Brownout + one sim), ≥4 h, only if core is solid by Sat 5 PM; the thin ACP wrapper idea is dropped.
- 2026-10-23 20:32 — Aryen's rule: no dead code, no hardcoding, no simulated data; everything genuine. Sim fallback removed from the demo; simulators are a developer test harness only (`--mode sim`, `tests/`), banner-labelled, never started by `make demo`, never in any reported number. No canned plans or prose. Stretch features are absent from the tree until built. Fetch multi-facility, if built, uses the laptop GPU as a real second facility, not a sim.
- 2026-10-23 20:55 — Reframe (Aryen): Brownout is a grid-aware compute DISPATCHER (live ISO prices/forecast/fuel mix/alerts → CP-SAT schedule over 24 h → execution on this Mac → measured verification), not a facility throttle. Demo on this MacBook only; no external hardware; teammates' machines for prep only. Power via powermetrics; knobs are concurrency, pause/resume, threads, GPU/CPU; no clock lock. Live keyless grid data verified via gridstatus from the venue at 8:50 PM (CAISO RT5 LMP, load forecast, fuel mix; ERCOT real-time conditions). Bold claim verified and reworded: during Winter Storm Fern (Jan 2026) the federal response for data centers was to order backup diesel generators, not shed compute.
- 2026-10-23 20:55 — Honest odds given to Aryen: Microsoft Grand Prize 25–35% as a concept, ~50% with clean execution and an operator quote; Fetch 15–20% only as a real three-agent flow; SpaceXSI skipped.

- 2026-10-23 22:51 — `make probe` on the demo Mac (output below, gridstatus debug lines removed). powermetrics OK, MPS OK, CAISO RT5 OK, ortools/torch/gridstatus/fastapi OK. Ollama 0.40.9 installed but no model yet (see the network entry). agent_framework not installed: it is the `[azure]` extra, needed from M5.
```
== machine
Apple M2 Pro
ProductName:		macOS
ProductVersion:		15.4.1
BuildVersion:		24E263
== powermetrics (needs sudo; two 1-second samples)
CPU Power: 559 mW
GPU Power: 60 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 619 mW
GPU Power: 60 mW
CPU Power: 395 mW
GPU Power: 222 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 617 mW
GPU Power: 222 mW
== ollama
ollama version is 0.40.9
NAME    ID    SIZE    MODIFIED 
== python
interpreter: /Users/AryenP/Library/Application Support/Claude/scratch-workspaces/f128f017-5645-4b80-984b-019e39d0fa8a/e2aef85f-8ca6-43e2-9534-dd1e1658a179/scratch-2026-10-24-7bcdbb/brownout/.venv/bin/python 3.11.5
torch: ok 2.14.1
ortools: ok 9.15.6755
gridstatus: ok 0.37.0
fastapi: ok 0.141.1
anthropic: ok 1.17.0
agent_framework: MISSING (ModuleNotFoundError)
pandas: ok 2.3.3
pydantic: ok 2.14.1
MPS available: True
CAISO SP15 RT5: 2026-10-23 22:50:00-07:00 50.33328 $/MWh
```
- 2026-10-23 22:51 — Idle SoC power on this M2 Pro reads ~0.62 W combined, well under RESEARCH.md's 3–8 W guess. It is SoC-only (CPU+GPU+ANE) as reported by macOS, not a wall meter. All job watts are deltas above a measured idle floor; nothing is typed.
- 2026-10-23 22:55 — macOS 15.4 powermetrics prints `GPU Power` twice per sample (again after `Combined Power`). The meter splits samples on the `*** Sampled system activity` header only and drops partial blocks; tested in tests/test_meter.py.
- 2026-10-23 22:55 — sudo's credential cache is per terminal on this Mac. The meter runs `sudo -n powermetrics` and never prompts, so anything that meters (`make demo`, `make calibrate`, `make baseline`) must be started from a terminal where `sudo -v` just ran. The Makefile targets already do `sudo -v &&` first.
- 2026-10-23 21:40 — PJM in gridstatus 0.37 needs a Data Miner API key (`PJM_API_KEY`); it is not keyless as SPEC assumed. PJM is offered only when the key is set (`core.config.available_isos`). CAISO and ERCOT verified keyless from the venue tonight.
- 2026-10-23 21:40 — ERCOT shapes differ from CAISO: prices via `get_spp` (column `SPP`, filter Trading Hub), load forecast column `System Total` republished hourly (keep newest), fuel mix has only `Time` and names `Coal and Lignite`, `Hydro`, `Power Storage`. Adapters in grid/isos.py normalise all three; emission factors added for the ERCOT names.
- 2026-10-23 22:50 — Schedule slots are in the ISO's local time (`timezone` in isos.yaml); 96 × 15 min. At night CAISO's day-ahead covers the whole horizon (tomorrow's DAM is out by ~1 PM), so the price curve is DAY_AHEAD_HOURLY end to end; otherwise the last RT price is held flat and the curve source says so.
- 2026-10-23 22:50 — Carbon: live fuel mix × factors in isos.yaml for "now"; the 24-h carbon curve is that value held flat and flagged `carbon_curve_is_proxy`. With a flat carbon curve only price varies across slots, and the solver's explanation says so. Emission-factor source still needs citing in isos.yaml before the demo (open item).
- 2026-10-23 23:10 — Deadline past the 24-h horizon (train is due Mon 9 AM) or no deadline (batch): plan to finish within the horizon. Conservative; the rolling re-solve moves the horizon forward. Logged in every schedule's explanations.
- 2026-10-23 23:20 — Runtimes are derived, not typed: train has `target_steps` (owner's ask), batch is its corpus; required minutes = remaining work / measured GPU rate from `make calibrate`; progress read from checkpoint sidecars. `required_runtime_min` removed from jobs.yaml.
- 2026-10-23 23:20 — Real data for the workloads, all local: train is a char-level transformer LM over /usr/share/dict/web2a; batch embeds macOS man pages (roff stripped) cut into 200-word passages = 18,794 items with all-MiniLM-L6-v2. Measured throughput is high (~6k short items/s on MPS), so batch is minutes of work, not 45; a bigger real corpus needs a download.
- 2026-10-23 23:20 — Device switch is checkpoint + reload on the other device inside the same process (same effect as SPEC's restart-from-checkpoint, faster). CPU training measured ~4.8 vs ~17.6 steps/s on MPS in the smoke test.
- 2026-10-23 23:25 — Venue bandwidth collapsed for bulk downloads (~145 KB/s; CAISO's small requests still fine). qwen3:4b pull restarted twice; two overlapping retry loops corrupted the partial download once (cleared and restarted). Chat calibration waits for the model; train/batch calibrated without it.
- 2026-10-23 23:00 — Python pinned to 3.11 (`.python-version`), packages declared in pyproject (setuptools could not auto-discover the flat layout). Test fixtures in tests/fixtures are a real CAISO pull, labelled in each file.
