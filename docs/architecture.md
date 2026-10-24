# Architecture

GitHub renders the diagram below. SPEC.md has the full interfaces; HANDOFF.md the API contract.

```mermaid
flowchart LR
  subgraph Grid["Live grid (gridstatus, keyless)"]
    ISO["CAISO / ERCOT<br/>RT + day-ahead prices, load forecast,<br/>fuel mix, system conditions"]
  end
  subgraph People
    U["Utility / operator<br/>OpenADR JSON or plain text"]
    O["Job owner<br/>phone: web/owner.html"]
    J["Chat users<br/>web/chat.html"]
  end
  ISO --> W["grid.watcher<br/>GridSignal: $/MWh, gCO2/kWh, age"]
  U --> I["agent.intake (LLM)<br/>CapEvent / Policy + read-back"]
  W --> S["dispatcher.solve<br/>OR-Tools CP-SAT, 24 h x 15 min"]
  I --> S
  S -- "deadline would slip" --> N["agent.negotiator (LLM)"]
  N <--> O
  N -- "approve / refuse / new deadline" --> S
  S --> C["controller.execute<br/>run/pause, concurrency, GPU/CPU"]
  C --> K["Workloads on the Mac<br/>chat (Ollama) · train (MPS) · batch"]
  J --> K
  K -. "power" .-> M["meter.powermetrics<br/>measured W, 1 Hz"]
  W & S & C & M & I & N --> T[("runs/&lt;id&gt;/timeline.jsonl")]
  T --> D["Dashboard (WebSocket)"]
  T --> R["agent.reporter + scripts/compare.py<br/>report and comparison"]
  I & N & S -. "OpenTelemetry spans" .-> OT["telemetry/<br/>ring buffer → /api/trace"]
  OT -. "Azure Monitor exporter" .-> AI["Azure Application Insights<br/>(azd provision)"]
```

Rules the diagram encodes:
- The LLM (intake, negotiator, explainer) returns data only; the solver decides and the controller executes.
- Only `powermetrics` produces watts; only the ISO feeds produce prices and fuel mix.
- Reports and comparisons read the timeline and nothing else.
