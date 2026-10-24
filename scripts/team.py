"""Who am I on this team, and does my branch only touch files I own?

    uv run python scripts/team.py whoami            # identify this machine from gh login / git email
    uv run python scripts/team.py check             # files changed vs origin/main must be mine
    uv run python scripts/team.py owner web/app.js  # who owns a path

Identity: `gh api user` login first, then `git config user.email`; `--member N` overrides.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

import yaml

ROSTER = Path(__file__).resolve().parents[1] / "team" / "roster.yaml"


def roster() -> dict:
    return yaml.safe_load(ROSTER.read_text())


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def identify(number: int | None = None) -> dict | None:
    members = roster()["members"]
    if number is not None:
        return next((m for m in members if m["number"] == number), None)
    login = _run("gh", "api", "user", "--jq", ".login").lower()
    email = _run("git", "config", "user.email").lower()
    for m in members:
        if login and login == m["github"].lower():
            return m
    for m in members:
        if email and email in [e.lower() for e in m["emails"]]:
            return m
    return None


def owners(path: str) -> list[dict]:
    return [m for m in roster()["members"] if any(fnmatch.fnmatch(path, g) for g in m["owns"])]


def changed_files(base: str) -> list[str]:
    mb = _run("git", "merge-base", base, "HEAD") or base
    out = _run("git", "diff", "--name-only", mb) + "\n" + _run("git", "ls-files", "--others", "--exclude-standard")
    return sorted({f for f in out.splitlines() if f})


def check(me: dict, base: str) -> list[str]:
    shared = roster().get("shared_append_only", [])
    bad = []
    for f in changed_files(base):
        if f in shared:
            continue
        if not any(fnmatch.fnmatch(f, g) for g in me["owns"]):
            who = ", ".join(f"{m['number']} {m['name']}" for m in owners(f)) or "nobody (ask machine 1 to assign it)"
            bad.append(f"{f}  (owned by {who})")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["whoami", "check", "owner"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--member", type=int)
    ap.add_argument("--base", default="origin/main")
    a = ap.parse_args(argv)
    if a.cmd == "owner":
        for m in owners(a.path or ""):
            print(f"{a.path}: {m['number']} {m['name']} ({m['role']})")
        return 0
    me = identify(a.member)
    if me is None:
        print("Could not tell who this machine is from `gh api user` or `git config user.email`.\n"
              "Ask the human which number they are (1 Aryen, 2 Anuraag, 3 Krish, 4 Arumalla) and pass --member N.")
        return 2
    if a.cmd == "whoami":
        br = "commit to main and merge PRs" if me["branch_prefix"] == "main" else f"branches {me['branch_prefix']}<task>"
        print(f"You are {me['number']} {me['name']} ({me['role']}). Assignment: {me['assignment']}; {br}.")
        return 0
    bad = check(me, a.base)
    if bad:
        print(f"{me['name']} changed files they do not own; move these changes to a PR note for the owner:")
        print("\n".join("  " + b for b in bad))
        return 1
    print(f"ok: every changed file is owned by {me['number']} {me['name']} or is shared append-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
