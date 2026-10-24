# Architecture

GitHub renders the diagram below. SPEC.md has the full interfaces; HANDOFF.md the API contract.

```mermaid
flowchart LR
  subgraph Grid["Live grid (gridstatus; CAISO, ERCOT keyless, PJM with PJM_API_KEY)"]
    ISO["CAISO / ERCOT<br/>RT + day-ahead prices, load forecast,<br/>fuel mix, system conditions"]
  end
  subgraph People
    U["Utility / operator<br/>OpenADR JSON or plain text"]
    O["Job owner<br/>phone: web/owner.html"]
    J["Chat users<br/>web/chat.html"]
  end
  ISO --> W["grid.watcher<br/>GridSignal: $/MWh, gCO2/kWh, age"]
  U --> I["agent.intake (rules first, LLM for messy text)<br/>CapEvent / Policy + read-back"]
  W --> S["dispatcher.solve<br/>OR-Tools CP-SAT, 24 h x 15 min"]
  I --> S
  S -- "deadline would slip" --> N["agent.negotiator (LLM)"]
  N <--> O
  N -- "approve / refuse / new deadline" --> S
  S --> C["controller.execute<br/>run/pause, concurrency, GPU/CPU"]
  C --> K["Workloads on the MacBook (M2 Pro)<br/>chat (Ollama qwen3:4b-instruct, streamed) · train (MPS) · batch"]
  J --> K
  K -. "power" .-> M["meter.powermetrics<br/>measured SoC W, 1 Hz"]
  W & S & C & M & I & N --> T[("runs/&lt;id&gt;/timeline.jsonl")]
  T --> D["Dashboard (WebSocket)"]
  T --> R["agent.reporter + scripts/compare.py<br/>Report, Comparison (/api/report, /api/compare)"]
  I & N & S -. "OpenTelemetry spans" .-> OT["telemetry/<br/>ring buffer → /api/trace"]
  OT -. "Azure Monitor exporter" .-> AI["Azure Application Insights<br/>(azd provision)"]
```

Rules the diagram encodes:
- The LLM (intake, negotiator, explainer) returns data only; the solver decides and the controller executes.
- Only `powermetrics` produces watts; only the ISO feeds produce prices and fuel mix.
- Reports and comparisons read the timeline and nothing else.
