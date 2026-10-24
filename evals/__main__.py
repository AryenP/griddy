"""`uv run python -m evals [--live] [--out PATH | --no-write]`: run the agent-layer evals, print the pass-rate
table per category and every failure, and write the same as markdown to docs/judging/evals.md."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from evals.suite import ROOT, markdown, run, table


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m evals")
    ap.add_argument("--live", action="store_true", help="use the configured LLM (agent.llm.get_llm())")
    ap.add_argument("--out", default=str(ROOT / "docs" / "judging" / "evals.md"))
    ap.add_argument("--no-write", action="store_true", help="print only")
    args = ap.parse_args()

    result = asyncio.run(run(live=args.live))
    if args.live and result.mode == "offline":
        print("--live asked, but no LLM is configured (.env): ran offline")
    print(f"mode: {result.mode}, {len(result.rows)} cases\n")
    print(table(result))
    fails = [r for r in result.rows if r.status == "fail"]
    if fails:
        print(f"\nfailures ({len(fails)}):")
        for r in fails:
            print(f"  [{r.category}] {r.id} ({r.path}): {r.input!r}\n      expected {r.expected}\n      got      {r.got}")
    if not args.no_write:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown(result, datetime.now().astimezone()), encoding="utf-8")
        print(f"\nwrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


if __name__ == "__main__":
    main()
