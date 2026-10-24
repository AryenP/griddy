#!/usr/bin/env bash
# What this Mac supports. Run first; paste output into DECISIONS.md.
set -u
echo "== machine"; sysctl -n machdep.cpu.brand_string 2>/dev/null; sw_vers 2>/dev/null
echo "== powermetrics (needs sudo; two 1-second samples)"
sudo powermetrics --samplers cpu_power,gpu_power -i 1000 -n 2 2>/dev/null | grep -E "CPU Power|GPU Power|ANE Power|Combined Power" || echo "powermetrics failed: run 'sudo -v' first"
echo "== ollama"; ollama --version 2>/dev/null && ollama list 2>/dev/null | head -5 || echo "ollama missing: brew install ollama && ollama pull qwen3:4b-instruct"
echo "== python"
# Use the project venv when it exists so the probe sees the same packages the app does.
PYBIN="python3"; [ -x .venv/bin/python ] && PYBIN=".venv/bin/python"
"$PYBIN" - <<'PY'
import sys; print("interpreter:", sys.executable, sys.version.split()[0])
import importlib
for m in ["torch","ortools","gridstatus","fastapi","anthropic","agent_framework","pandas","pydantic"]:
    try:
        mod=importlib.import_module(m); print(f"{m}: ok {getattr(mod,'__version__','')}")
    except Exception as e: print(f"{m}: MISSING ({e.__class__.__name__})")
try:
    import torch; print("MPS available:", torch.backends.mps.is_available())
except Exception: pass
try:
    import gridstatus
    df=gridstatus.CAISO().get_lmp(date="today", market="REAL_TIME_5_MIN", locations=["TH_SP15_GEN-APND"])
    r=df.iloc[-1]; print("CAISO SP15 RT5:", r["Interval Start"], float(r["LMP"]), "$/MWh")
except Exception as e: print("gridstatus pull failed:", repr(e)[:200])
PY
