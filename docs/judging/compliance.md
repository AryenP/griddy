# What the rules ask, what Brownout answers, what is missing

Requirements are quoted from `RESEARCH.md` "Why a utility can order this" (**R**); Brownout's evidence from
`DECISIONS.md` (**D hh:mm**). This is a hackathon prototype on one laptop: it shows the loop a compliant site
needs, not compliance itself.

| Rule (R) | What it requires | What Brownout does | Still missing |
|---|---|---|---|
| **Texas PUCT Docket 59220** (24 Jul 2026) | co-located data centers must fully curtail on ERCOT instruction; ≥60 min notice "when practicable"; 30-minute full-curtail capability, uncompensated | ERCOT feed live, including system conditions with a frequency alert rule (D 00:35, `config/isos.yaml`); a cap from text or OpenADR re-plans at once and the executor applies it at the slot boundary, measured under a 15 W cap within ~4 s (D 23:45); time to compliance is reported per event | full curtailment as a cap of 0 W for everything but the floor (needs an operator decision on chat); ERCOT end to end with the meter **to be measured** (D 00:35) |
| **Texas SB6** (2025) | loads ≥75 MW remotely disconnectable in firm load shed | a remote command path exists (`POST /api/event`, `POST /openadr/event`) and every action is logged | a hardware disconnect is outside software; Brownout covers the controllable part of the load |
| **PJM Board** (16 Jan 2026) | new large loads ≥50 MW not paired with generation are curtailed before pre-emergency DR; load-shed rules due end-2026 | the same cap path; PJM prices supported when `PJM_API_KEY` is set (D 21:40) | PJM not exercised live (no key at the venue) |
| **FERC show-cause** (18 Jun 2026) | RTOs must consider non-firm/interim service for flexible large loads ≥50 MW | a measured record of flexibility: dispatched vs dispatcher-off under the same call, 0 % vs 99 % of seconds at or under the cap, time to compliance 7 s (D 03:10) | a record at site scale and over many events (**to be measured**) |
| **DOE §403 directive** (23 Oct 2025) | loads that accept curtailment get expedited interconnection studies | the same record: the timeline proves each event (cap, actions, measured watts, approvals) | an interconnection-grade evidence format (interval meter data, see [production.md](production.md)) |
| **EPRI DCFlex** (via Reuters, 8 Oct 2026) | 10–30 % peak-reduction potential | the evidence runs used a 30 % cut of the measured baseline: Brownout held it with deadlines intact in the clean runs (D 02:28, D 03:10) | the three-policy run showed 69 % of seconds under the cap because of load outside the plan; fix landed, re-run **to be measured** (D 03:55) |

## How programs verify, and how Brownout reports it
R ("How compliance is verified in real programs"): revenue-grade interval meter data (5–15 min), performance
against a baseline, real-time telemetry, penalties on shortfall. Brownout's reporter computes from the timeline
only: the pre-event baseline (mean measured W before the cap), event-window mean, % reduction, time to compliance
(first second the 10-s mean is at or under the cap) and approvals with names and times (`agent/reporter.py`;
receipts on the dashboard). The meter is SoC power from macOS powermetrics, not a revenue meter (D 22:51).
