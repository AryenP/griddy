# Run Griddy yourself

Three ways in, shortest first. Only the third measures your own Mac.

| Way | Takes | Needs | What you see |
|---|---|---|---|
| 1. Chat with the agents | 2 min | a browser | Griddy's three Fetch.ai agents, answering from the demo Mac at our table |
| 2. Recompute our numbers | 5 min | Windows, Linux or macOS; no keys | every published measured number recomputed from the raw logs, the tests, the offline evals |
| 3. Run it on your Mac | about 20 min, mostly downloads and a 6-minute calibration | an Apple-silicon Mac and your admin password | the live grid, your Mac's own measured watts, the dispatcher, the dashboard |

## 1. Chat with the agents

On [agentverse.ai](https://agentverse.ai) open **Griddy Grid Desk**, then **Chat with Agent**. The steps and the three
addresses are in [README.md](../../README.md#fetchai-agents). The agents answer from the runtime on our demo Mac. When
it is off, they say the runtime is not answering and give no number.

## 2. Recompute our numbers (no Mac)

README.md, "Try it without a Mac": `uv sync --extra dev`, then `scripts/verify.py`, `pytest` and the offline evals.
On a fresh clone `make verify` reports 82 of 82 checks passing, from 10 raw timelines.

## 3. Run it on your Mac

### What you need

| | Why | Get it | Without it |
|---|---|---|---|
| Apple-silicon Mac, macOS 15 | powermetrics reads the chip's watts; training runs on the Apple GPU (PyTorch MPS) | — | No way around it: use way 2. Measured on an M2 Pro with macOS 15.4.1 |
| Xcode command line tools | `make`, `git` | `xcode-select --install` | — |
| uv | builds `.venv` with Python 3.11 (it downloads Python itself) | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) | — |
| Ollama and `qwen3:4b-instruct` (2.5 GB) | the chat workload, one of the three measured jobs | [ollama.com/download](https://ollama.com/download) | Required: chat is one of the three jobs `make calibrate` measures |
| Your admin password | powermetrics runs as root | — | Required. `make` asks for it once per terminal |
| About 6 GB free | the model, `.venv`, run logs | — | — |
| EIA key, free and instant | live replays of the grid emergencies | [eia.gov/opendata/register.php](https://www.eia.gov/opendata/register.php) | Replays use the public DEMO_KEY, then the stored copy of the EIA data, and the page says which |
| Anthropic key | reads free-text requests and owner replies, writes the explanations | [console.anthropic.com](https://console.anthropic.com) | "agent offline". Plain forms ("30% for 20 minutes", "yes", "no, <reason>") and OpenADR JSON are still read by rules; explanations are the solver's facts word for word |
| Optional: Azure AI Foundry | the same role through Microsoft Agent Framework | `uv pip install -e '.[azure]'`, then `AZURE_AI_PROJECT_ENDPOINT` and `AZURE_MODEL_DEPLOYMENT` | the Anthropic path, or "agent offline" |
| Optional: PJM key | the PJM grid | [dataminer2.pjm.com](https://dataminer2.pjm.com) | PJM is hidden. CAISO and ERCOT need no key |
| Optional: Agentverse key | your own copies of the three agents | [agentverse.ai](https://agentverse.ai), profile menu, API Keys | not needed to chat with ours (way 1) |

### Steps

```bash
git clone https://github.com/AryenP/griddy.git && cd griddy
make judge                      # checks only: what is missing, and the command for each
make setup                      # .venv with the runtime, PyTorch and sentence-transformers
cp .env.example .env            # add EIA_API_KEY and ANTHROPIC_API_KEY if you have them; never commit .env
make ollama                     # starts the Ollama server, if the Ollama app is not already running it
ollama pull qwen3:4b-instruct   # 2.5 GB. Plain qwen3:4b prints its reasoning into replies
make judge                      # everything but calibration should pass now
make calibrate                  # about 6 minutes, Mac otherwise idle: your idle watts, then each job's
make demo                       # the dashboard on http://localhost:8080
```

`make judge` reads only: it installs nothing, downloads nothing and never prints a key.

How long each step took on the demo Mac: `make calibrate` 5.5 minutes (run 20261024-134902-calibrate); `make setup`
10 seconds with uv's cache already full. A fresh Mac also downloads PyTorch and its dependencies, a few hundred MB.

### Once it runs

- **Dashboard**, http://localhost:8080: the live price and its age, the 24-hour plan, measured watts every second.
- **Operator page**, http://localhost:8080/operator.html: after the first minute, type `we need 30% off for 20
  minutes`. Griddy reads it back in watts from your measured baseline and re-plans; if a deadline would slip, it asks
  the job's owner first.
- **Replay** California's 2020 rotating outages or its 2022 heat wave from the EIA's hourly data, or Winter Storm Uri
  played on California's grid, labelled as a simulation.
- `make report` writes `reports/<run>.md` and a power chart from your run's log.

Your numbers will not match ours. Calibration measures your chip, and every watt on your screen is your Mac's own.

### Your own copies of the agents (optional)

Put `AGENTVERSE_API_KEY` in `.env`, add three seeds with the line in `.env.example`, and run `make fetch-three` with
`make demo` up. The agents register under your Agentverse account with new addresses. See
[fetch-three-agents.md](fetch-three-agents.md).

### If it fails

| You see | Do |
|---|---|
| `no calibration at runs/calibration.json` | `make calibrate` |
| `another run is measuring power on this Mac` | one measuring run at a time: stop the other `make demo` or `make calibrate` |
| `powermetrics exited ...` | run `sudo -v` in the same terminal, then the `make` target again |
| a port in use | `make judge` names it, with the command to find what holds it |
| "agent offline" on the dashboard | no Anthropic key or Azure endpoint in `.env`. Everything else still runs |

## Why there is no Docker image

Docker Desktop on a Mac runs containers inside a Linux virtual machine. That machine has no powermetrics, which reads
the Mac's own power sensors, and no access to the Apple GPU, so a container cannot measure a watt or run the GPU jobs.
Ollama in a container on a Mac runs on the CPU only. Griddy shows nothing it did not measure, so `make demo`,
`make calibrate` and the evidence runs cannot run in a container.

What a container could run, the tests, `make verify` and the offline evals, already runs natively on Windows, Linux
and macOS in a few minutes (way 2), so an image would add a step without saving one. The Fetch agents only talk to a
runtime on the same machine's loopback, which inside a container is the container. A copy of them would also be a new
agent with a new address: to judge ours, chat with ours (way 1).
