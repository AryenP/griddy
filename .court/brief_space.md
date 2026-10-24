# Variant on trial: Brownout-Orbit (power-aware agent for Earth-observation workloads)

Same builder, same 36-hour solo hackathon, same Microsoft Challenge Grand Prize target and criteria (customer understanding, measurable usefulness, path to production, responsible design, end-to-end). Same judges (Microsoft FDEs), same live 4-minute single-judge table demo. Read the base idea in brief.md first; this variant changes only the workloads and the customer.

## The variant
Customer: an Earth-observation analytics team that runs both time-sensitive processing (e.g., flood-extent maps for a region hit this week) and routine work (historical imagery reprocessing, background model training/evaluation). The power-aware agent keeps the team's compute under a changing electricity budget by prioritising the urgent satellite-image job, pausing or deferring the routine ones, obtaining approval for deadline changes, executing the revised plan, verifying actual consumption on an independent meter, and preserving completed progress.

Workloads on the box:
1. Urgent: flood segmentation inference on Sentinel-1 SAR imagery for a named region (Sen1Floods11 dataset: public, labelled, with published train/test splits; small U-Net or similar).
2. Routine: batch reprocessing of historical tiles (droppable/deferrable).
3. Background: model fine-tuning/evaluation on Sen1Floods11 with checkpointing (deferrable, owner approval).
Optionally the chat endpoint stays as the interactive SLA workload, or the urgent inference job takes that role (latency-to-first-map as the SLA).

Visible output the base idea lacks: an actual flood map appears on the dashboard while the meter drops.

## Extra prize this unlocks
Cal Hacks "SpaceXSI" sponsor track (verified on Devpost 23 Oct): "To be eligible, your project must be built with Cursor." Bonus points for using Grok Bot for planning/collaboration. Encourages large public space datasets. Prize: $400 cash plus a Cursor mechanical keyboard per member. No track-specific judging criteria. Note: the builder currently works in Claude Code; switching to Cursor is a tooling change, not a product change.

## What stays the same
Agent/controller split, action ladder, two meters, DR-style baseline and time-to-compliance, owner refusal moment, impossible-cap shortfall, OpenADR intake, Microsoft Agent Framework + App Insights, the prior-art and regulation evidence (Texas PUCT Docket 59220, PJM 50 MW rule, Emerald AI 25%/3 h, Google DR deals).

## New risks the builder sees
- Two hard things instead of one: a segmentation model that produces a believable flood map, plus the whole power-control stack, in 36 hours solo.
- Sen1Floods11 download size and preprocessing time on venue Wi-Fi.
- The customer is less universal than "a data center under a utility order"; an EO analytics team is a niche, and the builder has not spoken to one.
- Judges may ask why the urgent job should ever be power-managed at all (answer: it isn't; it's what gets protected).
- Three prize tracks pull in three directions (Microsoft production-mindedness, SpaceXSI space data, Planet-First impact).
