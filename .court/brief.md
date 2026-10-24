# The idea on trial: Brownout

Context: solo hacker, 36-hour hackathon (Cal Hacks 13.0, Oct 23–25 2026), targeting the Microsoft Challenge Grand Prize. Microsoft's criteria: (1) customer understanding, (2) measurable usefulness, (3) path from prototype to production, (4) responsible design, (5) end-to-end functionality. Judges are Microsoft forward-deployed engineers (Delta / Frontier Co.) who deploy agents into real enterprises. Judging is a live 3–4 minute table demo, Sunday morning; typically one judge per sponsor.

## One-sentence problem
AI data centers are maxing out the grid, and when a utility asks them to cut power they either refuse or shut everything off.

## Solution
Brownout is an agent that takes a utility's power-reduction request (OpenADR 3.1 event or plain-English email/voice), plans which workloads to slow, pause or defer based on priorities, deadlines and interruption permissions, asks the affected job owners for approval, drives a deterministic controller that actuates GPU clock limits / chat concurrency / checkpoint-and-pause, and proves the reduction with an independent wall meter next to the GPU's self-reported power. When the target is infeasible it reports the shortfall and the trade-offs instead of silently failing. After the event it writes the compliance report. The LLM never touches a power knob.

## Prototype
One NVIDIA GB10 box (ASUS Ascent GX10, ~90–120 W under load) or a laptop GPU, a Shelly/Kasa smart plug as the independent meter, three workloads: vLLM chat endpoint (interactive, protected SLA), a PyTorch training loop with checkpointing (deferrable), a batch embedding job (droppable). Knobs: nvidia-smi clock lock (power limit is likely unsupported on GB10), chat concurrency via a proxy semaphore, cooperative pause/checkpoint. Comparison against uniform throttling on: watts under cap, p95 chat latency, work completed, checkpoint recovery.

## Judge demo (single judge plays every role)
1. Judge chats with the model from their phone; meter on the table reads ~100 W.
2. "You're the utility": judge writes/says "cut 30% for ten minutes." Agent reads back a plan and asks the job owner for approval.
3. Judge's phone buzzes as the job owner; they refuse. Agent re-plans: "Without pausing training I reach X not Y; slow chat by ~1 s or drop the embedding job?" Judge picks. Meter drops; chat still fast.
4. Judge plugs a lamp into the same metered strip. Meter jumps; agent tightens compute within seconds to stay under cap.
5. Judge asks for 90%. Agent: "Can't; floor for chat is N W (47%). Approve going dark on everything else or accept 47%?" Shortfall report shown.
6. Release: training resumes from checkpoint; dashboard shows work saved vs the uniform-throttle baseline.

## Evidence the builder will cite
- Texas PUCT Docket 59220 (Jul 2026): co-located data centers must fully curtail on ERCOT instruction within 30 minutes, uncompensated. PJM (Jan 2026): new ≥50 MW loads without own generation are curtailed first in emergencies. FERC show-cause orders (Jun 2026) on flexible large loads.
- Emerald AI (Nvidia-backed, $24.5M seed) cut a GPU cluster 25% for 3 h in Phoenix (2025). Google signed ML-workload demand-response deals (Aug 2025). Google/Nvidia/Emerald "AI Energy Management Alliance" (Sep 2026). OpenAI agreed to shed up to 1 GW in Georgia. EPRI: 10–30% peak reduction potential.
- Microsoft's Jul 2026 "least privilege for AI agents" guidance: dedicated agent identity, tool allowlists, step-up human approval, audit logs. Foundry Agent Control Specification: deterministic controls at tool checkpoints.

## Known weaknesses the builder already admits
- A single ~100 W box is a toy next to a 100 MW campus; the demo swing is tens of watts.
- Emerald AI and Google already do the real thing at scale; the hackathon differentiator is the agent layer + independent verification + shortfall negotiation.
- nvidia-smi power limit may not work on GB10; clock locking is the knob. Smart-plug meters update ~1 Hz.
- Solo builder; Teams integration unrealistic in 36 h (Slack/web console in demo, Teams as production path).
- "Customer understanding" rests on regulation and press, not on a conversation with a data-center operator (builder plans to talk to Microsoft FDEs Saturday).
