"""Fail if runtime code (anything a judge's run executes) contains fabricated-data markers:
mock/fake/dummy identifiers or random-number generators. Tests are exempt (labelled fixtures).

    uv run python scripts/check_runtime.py        # CI runs this on every PR and push
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ["api", "controller", "dispatcher", "grid", "meter", "workloads", "core", "agent", "telemetry", "web",
           "fleet", "neighbourhood"]
PATTERN = re.compile(r"\b(mock|fake|dummy)\w*\b|\brandom\.(random|uniform|randint|choice|gauss|sample)\b|np\.random\.",
                     re.IGNORECASE)
SUFFIXES = {".py", ".js", ".html", ".yaml", ".yml", ".json"}


def scan() -> list[str]:
    hits = []
    for d in RUNTIME:
        for f in sorted((ROOT / d).rglob("*")):
            if f.suffix not in SUFFIXES or "__pycache__" in f.parts:
                continue
            for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if PATTERN.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    return hits


if __name__ == "__main__":
    hits = scan()
    if hits:
        print("Fabricated-data markers in runtime code (move to tests/ or use real data):")
        print("\n".join("  " + h for h in hits))
        sys.exit(1)
    print(f"ok: no mock/fake/dummy/random markers in {', '.join(RUNTIME)}")
