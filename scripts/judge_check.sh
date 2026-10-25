#!/usr/bin/env bash
# Can this Mac run Griddy? One line per check, PASS / WARN / FAIL / SKIP, with the fix underneath.
#
#     make judge        # = bash scripts/judge_check.sh   (docs/judging/run-it-yourself.md)
#
# Needs nothing installed beyond macOS, so it runs before `make setup`. It only reads: no installs, no downloads,
# no writes. Keys in .env are checked for being set and never printed. Exit 1 if anything FAILs.
set -u
cd "$(dirname "$0")/.." || exit 1

fails=0; warns=0; todo=()
row() {  # status, name, detail, [fix]
  printf '%-5s %-14s %s\n' "$1" "$2" "$3"
  [ -n "${4:-}" ] && printf '%-5s %-14s -> %s\n' "" "" "$4"
  case $1 in FAIL) fails=$((fails + 1)); todo+=("${4:-}");; WARN) warns=$((warns + 1));; esac
}
# KEY's value in .env as python-dotenv reads this file: unquoted, an inline "# comment" dropped
envval() {
  [ -f .env ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env | tail -1 |
    sed -E 's/(^|[[:space:]]+)#.*$//; s/^["'\'']//; s/["'\'']$//; s/[[:space:]]+$//'
}
PYBIN=python3; [ -x .venv/bin/python ] && PYBIN=.venv/bin/python

# -- the machine: the measured core is macOS powermetrics and PyTorch on the Apple GPU
if [ "$(uname -s)" != Darwin ]; then
  row FAIL machine "$(uname -s): powermetrics exists only on macOS" \
      "this machine runs the keyless path: README.md, \"Try it without a Mac\""
  echo; echo "1 FAIL => the tests and make verify run here, not the live demo"; exit 1
fi
chip=$(sysctl -n machdep.cpu.brand_string 2>/dev/null); macos=$(sw_vers -productVersion)
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = 1 ]; then
  row PASS machine "$chip, macOS $macos"
else
  row FAIL machine "$chip: not Apple silicon; Griddy needs PyTorch 2.4+, which has no Intel-Mac builds" \
      "this Mac runs the keyless path: README.md, \"Try it without a Mac\""
fi
case $macos in
  1[5-9].*|1[5-9]|2[0-9]*) ;;
  *) row WARN macOS "$macos: Griddy was measured on macOS 15.4.1; older powermetrics output may differ" ;;
esac
if xcode-select -p >/dev/null 2>&1; then row PASS "command tools" "make and git ($(xcode-select -p))"
else row FAIL "command tools" "no Xcode command line tools, so no make or git" "xcode-select --install"; fi

# -- Python: uv builds .venv with Python 3.11 (.python-version) on its own
if command -v uv >/dev/null; then row PASS uv "$(uv --version)"
else row FAIL uv "not installed" "curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)"; fi
if [ -x .venv/bin/python ] && .venv/bin/python -c "import fastapi, ortools, gridstatus, torch, sentence_transformers" 2>/dev/null; then
  if [ "$(.venv/bin/python -c 'import torch; print(torch.backends.mps.is_available())' 2>/dev/null)" = True ]; then
    row PASS "python env" ".venv has the runtime and the Mac extras; MPS available"
  else
    row FAIL "python env" ".venv is set up, but torch sees no Apple GPU (MPS)" \
        "check the terminal is not running under Rosetta, then: rm -rf .venv && make setup"
  fi
else
  row FAIL "python env" "no .venv with the runtime and the Mac extras (torch, sentence-transformers)" "make setup"
fi

# -- .env and what each key adds; with none of them the measured core still runs
if [ ! -f .env ]; then
  row FAIL .env "missing" "cp .env.example .env"
else
  row PASS .env "present"
  if [ -n "$(envval EIA_API_KEY)" ]; then row PASS "EIA key" "set: replays fetch their hours live from api.eia.gov"
  else row WARN "EIA key" "empty: replays use the public DEMO_KEY, then the stored EIA copy, and say so on screen" \
      "free and instant: https://www.eia.gov/opendata/register.php, then EIA_API_KEY=... in .env"; fi
  if [ -n "$(envval ANTHROPIC_API_KEY)" ] || [ -n "$(envval AZURE_AI_PROJECT_ENDPOINT)" ]; then
    row PASS "agent model" "a key or endpoint is set"
  else row WARN "agent model" "none: 'agent offline'; plain requests, yes / no replies and OpenADR are still read by rules" \
      "ANTHROPIC_API_KEY=... in .env (https://console.anthropic.com)"; fi
  if [ -z "$(envval AGENTVERSE_API_KEY)" ]; then
    row SKIP "fetch agents" "no AGENTVERSE_API_KEY: not needed to chat with Griddy's agents on agentverse.ai"
  else
    missing=""; for r in GRID_DESK FACILITY VERIFIER; do [ -n "$(envval "FETCH_${r}_SEED")" ] || missing="$missing $r"; done
    if [ -n "$missing" ]; then
      row WARN "fetch agents" "AGENTVERSE_API_KEY set, no seed for:$missing" \
          "for r in$missing; do printf 'FETCH_%s_SEED=%s\\n' \"\$r\" \"\$(openssl rand -hex 32)\" >> .env; done"
    else row PASS "fetch agents" "key and three seeds set: make fetch-three runs your own copies"; fi
  fi
fi

# -- Ollama: the chat workload. The model is checked on disk, so the server need not be up yet
model=$(envval OLLAMA_MODEL); model=${model:-qwen3:4b-instruct}
name=${model%%:*}; tag=${model#"$name"}; tag=${tag#:}; tag=${tag:-latest}
manifest="${OLLAMA_MODELS:-$HOME/.ollama/models}/manifests/registry.ollama.ai/library/$name/$tag"
if ! command -v ollama >/dev/null; then
  row FAIL ollama "not installed: the chat workload runs on it" "brew install ollama   (or the app: https://ollama.com/download)"
else
  ollama_url=$(envval OLLAMA_URL); ollama_url=${ollama_url:-http://localhost:11434}
  if curl -fsS -m 3 "${ollama_url%/}/api/tags" >/dev/null 2>&1; then row PASS ollama "server up at $ollama_url"
  else row PASS ollama "installed; make demo starts the server"; fi
  if [ -f "$manifest" ]; then row PASS "chat model" "$model pulled"
  else row FAIL "chat model" "$model not pulled" "make ollama && ollama pull $model   (2.5 GB)"; fi
fi

# -- what the workloads read, and room to write
if [ -r /usr/share/dict/web2a ] && ls /usr/share/man/man1/*.1 >/dev/null 2>&1; then
  row PASS corpora "/usr/share/dict/web2a (training) and the man pages (embeddings) are there"
else
  row FAIL corpora "/usr/share/dict/web2a or /usr/share/man is missing: training and embeddings read them (config/jobs.yaml)"
fi
free_gb=$(df -g . | awk 'NR==2 {print $4}')
if [ "$free_gb" -lt 3 ]; then row FAIL disk "$free_gb GB free" "free about 6 GB: the chat model is 2.5 GB, the environment about 1.5 GB"
elif [ "$free_gb" -lt 6 ]; then row WARN disk "$free_gb GB free: the chat model and the environment need about 4 GB"
else row PASS disk "$free_gb GB free"; fi
port=$(envval PORT); port=${port:-8080}
for p in "$port" 8090; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    row FAIL "port $p" "in use" "stop what listens on :$p (an earlier make demo?): lsof -nP -iTCP:$p -sTCP:LISTEN"
  else row PASS "port $p" "free"; fi
done

# -- power: powermetrics runs as root; the make targets ask for the password once per terminal
if sudo -n /usr/bin/powermetrics --samplers cpu_power,gpu_power -i 1000 -n 1 >/dev/null 2>&1; then
  row PASS sudo "powermetrics runs without a prompt in this terminal"
else
  row WARN sudo "powermetrics needs your password: make calibrate and make demo ask for it once"
fi
cal=$(envval CALIBRATION_PATH); cal=${cal:-runs/calibration.json}
here="$chip macOS $macos"
if [ ! -f "$cal" ]; then
  row FAIL calibration "$cal missing: make demo plans from this Mac's measured watts, never typed ones" \
      "with the Mac otherwise idle: make calibrate   (about 6 minutes)"
else
  cal_machine=$("$PYBIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["machine"])' "$cal" 2>/dev/null)
  cal_age_h=$("$PYBIN" -c 'import json,sys,time; print(int((time.time()-json.load(open(sys.argv[1]))["measured_at"])/3600))' "$cal" 2>/dev/null)
  if [ "$cal_machine" != "$here" ]; then
    row FAIL calibration "measured on '${cal_machine:-unreadable}', this is '$here'" \
        "with the Mac otherwise idle: make calibrate   (about 6 minutes)"
  elif [ "${cal_age_h:-99}" -gt 12 ]; then
    row WARN calibration "$cal_age_h h old: a fresh one matches today's background load" "make calibrate   (about 6 minutes)"
  else row PASS calibration "$here, $cal_age_h h old"; fi
fi

echo
if [ "$fails" -gt 0 ]; then
  echo "$fails FAIL, $warns WARN => not ready yet. In this order:"
  for f in "${todo[@]}"; do [ -n "$f" ] && echo "  $f"; done
  echo "  make demo"
  exit 1
fi
echo "$warns WARN => ready: make demo, then open http://localhost:$port"
