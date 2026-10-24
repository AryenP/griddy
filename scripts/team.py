"""Who am I on this team, and does my branch only touch files I own?

    uv run python scripts/team.py whoami --save       # identify this machine and remember it locally
    uv run python scripts/team.py check               # files changed vs origin/main must be mine
    uv run python scripts/team.py check --branch krish/reporter   # CI: identify by branch prefix
    uv run python scripts/team.py owner web/app.js    # who owns a path

Identity order: --member N, $BROWNOUT_MEMBER, .claude/member.local (written by --save), the
`gh api user` login, then `git config user.email`. The lane-guard hook uses the same order minus gh.
"""
from __future__ import annotations

import argparse
import functools
import re
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "team" / "roster.yaml"
LOCAL = ROOT / ".claude" / "member.local"


@functools.lru_cache(maxsize=None)
def _glob_re(glob: str) -> re.Pattern:
    """Path globs: `*` and `?` stay inside one folder, `**` crosses folders, `[..]` is a class."""
    out, i = "", 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out += "(?:.*/)?"; i += 3; continue
        if glob.startswith("**", i):
            out += ".*"; i += 2; continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        elif c == "[":
            j = glob.index("]", i)
            out += glob[i:j + 1]; i = j + 1; continue
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out + r"\Z")


def match(path: str, glob: str) -> bool:
    return bool(_glob_re(glob).match(path))


def roster() -> dict:
    return yaml.safe_load(ROSTER.read_text())


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def member(number: int) -> dict | None:
    return next((m for m in roster()["members"] if m["number"] == number), None)


def identify(number: int | None = None, network: bool = True, root: Path = ROOT) -> dict | None:
    if number is not None:
        return member(number)
    env = os.getenv("BROWNOUT_MEMBER", "").strip()
    if env.isdigit():
        return member(int(env))
    local = root / ".claude" / "member.local"
    if local.exists() and local.read_text().strip().isdigit():
        return member(int(local.read_text().strip()))
    members = roster()["members"]
    if network:
        login = _run("gh", "api", "user", "--jq", ".login").lower()
        for m in members:
            if login and login == m["github"].lower():
                return m
    email = _run("git", "-C", str(root), "config", "user.email").lower()
    for m in members:
        if email and email in [e.lower() for e in m["emails"]]:
            return m
    return None


def by_branch(branch: str) -> dict | None:
    for m in roster()["members"]:
        p = m["branch_prefix"]
        if p != "main" and branch.startswith(p):
            return m
    return None


def owners(path: str) -> list[dict]:
    return [m for m in roster()["members"] if any(match(path, g) for g in m["owns"])]


def allowed(me: dict, path: str) -> bool:
    return path in roster().get("shared_append_only", []) or any(match(path, g) for g in me["owns"])


def changed_files(base: str) -> list[str]:
    mb = _run("git", "merge-base", base, "HEAD") or base
    out = _run("git", "diff", "--name-only", mb) + "\n" + _run("git", "ls-files", "--others", "--exclude-standard")
    return sorted({f for f in out.splitlines() if f})


def check(me: dict, base: str) -> list[str]:
    bad = []
    for f in changed_files(base):
        if not allowed(me, f):
            who = ", ".join(f"{m['number']} {m['name']}" for m in owners(f)) or "nobody (ask machine 1 to assign it)"
            bad.append(f"{f}  (owned by {who})")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["whoami", "check", "owner"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--member", type=int)
    ap.add_argument("--branch", help="identify by branch prefix (CI)")
    ap.add_argument("--save", action="store_true", help="whoami: remember this machine in .claude/member.local")
    ap.add_argument("--base", default="origin/main")
    a = ap.parse_args(argv)
    if a.cmd == "owner":
        for m in owners(a.path or ""):
            print(f"{a.path}: {m['number']} {m['name']} ({m['role']})")
        return 0
    me = by_branch(a.branch) if a.branch else identify(a.member)
    if me is None:
        if a.branch:
            print(f"branch {a.branch!r} has no member prefix ({', '.join(m['branch_prefix'] for m in roster()['members'])})")
            return 1
        print("Could not tell who this machine is from `gh api user` or `git config user.email`.\n"
              "Ask the human which number they are (1 Aryen, 2 Anuraag, 3 Krish, 4 Arumalla), then run\n"
              "  uv run python scripts/team.py whoami --member N --save")
        return 2
    if a.cmd == "whoami":
        br = "commit to main and merge PRs" if me["branch_prefix"] == "main" else f"branches {me['branch_prefix']}<task>"
        print(f"You are {me['number']} {me['name']} ({me['role']}). Assignment: {me['assignment']}; "
              f"status file: team/status/{Path(me['assignment']).name}; {br}.")
        if a.save:
            LOCAL.parent.mkdir(exist_ok=True)
            LOCAL.write_text(f"{me['number']}\n")
            print(f"saved: {LOCAL.relative_to(ROOT)} (the lane-guard hook reads it)")
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
