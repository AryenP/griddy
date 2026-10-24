"""PreToolUse hook: block Claude's Edit/Write/NotebookEdit on files another machine owns
(team/roster.yaml). Exit 2 sends the reason back to Claude. A speed bump, not a wall: shell
commands can still write anywhere, which is why CI re-checks ownership on every PR."""
import json
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
ti = data.get("tool_input") or {}
target = ti.get("file_path") or ti.get("notebook_path")
if not target:
    sys.exit(0)
p = Path(target).expanduser().resolve()
start = p.parent if p.parent.exists() else Path.cwd()
top = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                     capture_output=True, text=True).stdout.strip()
if not top:
    sys.exit(0)                      # not inside a git checkout: not ours to police
top_p = Path(top).resolve()
try:
    rel = p.relative_to(top_p).as_posix()
except ValueError:
    sys.exit(0)                      # outside this checkout (another repo, scratch files)

sys.path.insert(0, str(top_p / "scripts"))
import team  # noqa: E402

if not (top_p / "team" / "roster.yaml").exists():
    sys.exit(0)
me = team.identify(network=False, root=top_p)
if me is None:
    print("Lane guard: this machine has no team identity yet. Run\n"
          "  uv run python scripts/team.py whoami --save\n"
          "(or --member N --save), then retry.", file=sys.stderr)
    sys.exit(2)
if team.allowed(me, rel):
    sys.exit(0)
who = ", ".join(f"{m['number']} {m['name']}" for m in team.owners(rel)) or "nobody yet (machine 1 assigns it)"
print(f"Lane guard: {rel} is owned by {who}, not {me['number']} {me['name']}. Do not edit it; write what you "
      f"need under 'Needs from others' in your PR description or team/status file.", file=sys.stderr)
sys.exit(2)
