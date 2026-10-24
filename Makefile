.PHONY: ollama setup demo baseline calibrate solve report compare test probe qr clean

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

solve:          ## print the 24-h schedule for the live price curve
	$(PY) python -m dispatcher.solve --print

report:         ## render compliance report + charts from a timeline
	$(PY) python -m agent.reporter --run $(RUN)

compare:        ## side-by-side numbers: workload-aware vs uniform
	$(PY) python scripts/compare.py

test:
	$(PY) pytest -q

probe:          ## what does this Mac support?
	bash scripts/probe_mac.sh | tee runs/probe-$$(date +%s).txt

qr:             ## print QR codes for the judge's phone (chat + owner console)
	$(PY) python scripts/qr.py

clean:
	rm -rf runs/* reports/* .pytest_cache
