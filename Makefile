.PHONY: preflight tag-stable ollama setup demo baseline calibrate chat-sweep solve report compare test probe qr clean

PY ?= uv run
RUN ?= latest

setup:
	uv venv && uv pip install -e ".[dev]"
	uv pip install -e ".[mac]"
	@echo "For Azure: uv pip install -e '.[azure]'"

ollama:         ## start the Ollama server with parallel slots >= chat max_concurrency, if not running
	@pgrep -x ollama >/dev/null || (mkdir -p runs/logs && OLLAMA_NUM_PARALLEL=$${OLLAMA_NUM_PARALLEL:-4} nohup ollama serve >> runs/logs/ollama-serve.log 2>&1 & sleep 2)

demo: ollama    ## live: grid feeds + powermetrics + workloads + dispatcher + dashboard
	sudo -v && $(PY) python -m api.app

baseline: ollama ## dispatcher off: same jobs, run-everything policy, for the comparison
	sudo -v && POLICY=baseline $(PY) python -m api.app --headless --duration 600

calibrate: ollama ## measure per-job watt deltas and the idle floor with powermetrics
	sudo -v && $(PY) python -m controller.feasibility --calibrate $(ARGS)

chat-sweep: ollama ## chat TTFT/total latency by concurrency x max_tokens (idle GPU, then with training)
	$(PY) python -m controller.feasibility --chat-sweep $(ARGS)

solve:          ## print the 24-h schedule for the live price curve
	$(PY) python -m dispatcher.solve --print

report:         ## render compliance report + charts from a timeline
	$(PY) python -m agent.reporter --run $(RUN)

compare:        ## side-by-side numbers: workload-aware vs uniform
	$(PY) python scripts/compare.py

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
