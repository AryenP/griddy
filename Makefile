.PHONY: evidence evidence3 preflight tag-stable ollama setup demo baseline calibrate chat-sweep solve report compare test probe qr clean

PY ?= uv run
# sudo for powermetrics: no prompt when the passwordless rule for /usr/bin/powermetrics is installed
# (team/README.md, "Unattended runs"); otherwise ask once and cache it for this terminal.
SUDO_PM = sudo -n /usr/bin/powermetrics --samplers cpu_power,gpu_power -i 1000 -n 1 >/dev/null 2>&1 || sudo -v
RUN ?= latest

setup:
	uv venv && uv pip install -e ".[dev]"
	uv pip install -e ".[mac]"
	@echo "For Azure: uv pip install -e '.[azure]'"

ollama:         ## start the Ollama server with parallel slots >= chat max_concurrency, if not running
	@pgrep -x ollama >/dev/null || (mkdir -p runs/logs && OLLAMA_NUM_PARALLEL=$${OLLAMA_NUM_PARALLEL:-4} nohup ollama serve >> runs/logs/ollama-serve.log 2>&1 & sleep 2)

demo: ollama    ## live: grid feeds + powermetrics + workloads + dispatcher + dashboard
	($(SUDO_PM)) && $(PY) python -m api.app

baseline: ollama ## dispatcher off: same jobs, run-everything policy, for the comparison
	($(SUDO_PM)) && POLICY=baseline $(PY) python -m api.app --headless --duration 600

calibrate: ollama ## measure per-job watt deltas and the idle floor with powermetrics
	($(SUDO_PM)) && $(PY) python -m controller.feasibility --calibrate $(ARGS)

chat-sweep: ollama ## chat TTFT/total latency by concurrency x max_tokens (idle GPU, then with training)
	$(PY) python -m controller.feasibility --chat-sweep $(ARGS)

solve:          ## print the 24-h schedule for the live price curve
	$(PY) python -m dispatcher.solve --print

EVIDENCE_ARGS ?= --cap-pct 30 --cap-at 120 --cap-for 300 --deadline train=2
evidence: ollama ## unattended (~25 min, Mac otherwise idle): calibrate, then dispatcher-off and dispatched runs from identical fresh job state with the same scripted cap, then compare
	($(SUDO_PM)) || exit 1; ( while sudo -n -v 2>/dev/null; do sleep 50; done ) & K=$$!; \
	E=runs/evidence-state-$$(date +%Y%m%d-%H%M%S); \
	$(PY) python -m controller.feasibility --calibrate && \
	BROWNOUT_CHECKPOINT_DIR=$$E/baseline POLICY=baseline $(PY) python -m api.app --headless --duration 450 $(EVIDENCE_ARGS) && \
	BROWNOUT_CHECKPOINT_DIR=$$E/dispatched $(PY) python -m api.app --headless --duration 450 $(EVIDENCE_ARGS) && \
	$(PY) python scripts/compare.py; s=$$?; kill $$K 2>/dev/null; exit $$s

EVIDENCE3_ARGS ?= --cap-pct 30 --cap-at 120 --cap-for 1800 --deadline train=1.87
evidence3: ollama ## unattended (~30 min): calibrate, then ignore-the-call, pause-everything and dispatched runs, same tight scenario, two comparisons
	($(SUDO_PM)) || exit 1; ( while sudo -n -v 2>/dev/null; do sleep 50; done ) & K=$$!; \
	E=runs/evidence-state-$$(date +%Y%m%d-%H%M%S); \
	$(PY) python -m controller.feasibility --calibrate && \
	BROWNOUT_CHECKPOINT_DIR=$$E/baseline POLICY=baseline $(PY) python -m api.app --headless --duration 450 $(EVIDENCE3_ARGS) && \
	BROWNOUT_CHECKPOINT_DIR=$$E/pause_all POLICY=pause_all $(PY) python -m api.app --headless --duration 450 $(EVIDENCE3_ARGS) && \
	BROWNOUT_CHECKPOINT_DIR=$$E/dispatched $(PY) python -m api.app --headless --duration 450 $(EVIDENCE3_ARGS) && \
	$(PY) python scripts/compare.py --baseline-policy baseline && \
	$(PY) python scripts/compare.py --baseline-policy pause_all; s=$$?; kill $$K 2>/dev/null; exit $$s

report:         ## render compliance report + charts from a timeline
	$(PY) python -m agent.reporter --run $(RUN)

compare:        ## dispatched vs baseline from logged runs (newest of each, or DISPATCHED=<id> BASELINE=<id>)
	$(PY) python scripts/compare.py $(if $(DISPATCHED),--dispatched $(DISPATCHED)) $(if $(BASELINE),--baseline $(BASELINE))

test:
	$(PY) pytest -q

tag-stable:     ## after a full live `make demo` worked end to end: tag it; demo from the newest tag
	$(PY) pytest -q && $(PY) python scripts/check_runtime.py
	n=$$(( $$(git tag -l 'demo-stable-*' | sed 's/demo-stable-//' | sort -n | tail -1) + 1 )); \
	git tag -a "demo-stable-$$n" -m "$(or $(MSG),end-to-end demo verified on the demo Mac)" && git push origin "demo-stable-$$n" && echo "tagged demo-stable-$$n"

preflight:      ## before the judge: is everything the demo needs ready? (machine 2 builds it)
	$(PY) python scripts/preflight.py

probe:          ## what does this Mac support?
	bash scripts/probe_mac.sh | tee runs/probe-$$(date +%s).txt

qr:             ## print QR codes for the judge's phone (chat + owner console)
	$(PY) python scripts/qr.py

clean:
	rm -rf runs/* reports/* .pytest_cache
