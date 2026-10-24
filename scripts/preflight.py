"""Pre-demo preflight: is everything the demo needs ready on this machine? One line per check, PASS / WARN /
FAIL / SKIP, with the fix in one line. Exit code 1 if anything FAILs.

    make preflight        # = uv run python scripts/preflight.py

Mac-only checks (calibration, sudo, the Mac extras) print SKIP elsewhere. Nothing here changes state: it only
reads files and probes (HTTP, ports, git, sudo -n). Agent keys are never printed."""
from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENV = ["ISO", "LOCATION", "OLLAMA_MODEL", "PUBLIC_URL"]
IMPORTS = ["fastapi", "uvicorn", "pydantic", "httpx", "yaml", "anthropic", "dotenv", "qrcode", "matplotlib",
           "opentelemetry", "gridstatus", "pandas", "ortools"]
MAC_IMPORTS = ["torch", "sentence_transformers"]
CALIBRATION_MAX_AGE_H = 12
DISK_FAIL_GB, DISK_WARN_GB = 2, 10
OASIS = "https://oasis.caiso.com/oasisapi/SingleZip"   # same query as scripts/verify_feed.py


@dataclass
class Check:
    name: str
    status: str            # PASS | WARN | FAIL | SKIP
    detail: str
    fix: str = ""


@dataclass
class Ctx:
    root: Path
    env: dict[str, str]
    jobs: dict = field(default_factory=dict)
    isos: dict = field(default_factory=dict)
    is_mac: bool = False
    env_file_exists: bool = True


# ---------------------------------------------------------------------------
# Probes: the only places that touch the network, processes or the OS. Tests replace these.
# ---------------------------------------------------------------------------

def http_get(url: str, params: dict | None = None, timeout: float = 5.0) -> httpx.Response:
    return httpx.get(url, params=params, timeout=timeout)


def http_post(url: str, payload: dict, timeout: float = 60.0) -> httpx.Response:
    return httpx.post(url, json=payload, timeout=timeout)


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def lan_ip() -> str | None:
    """The address this machine uses to reach the LAN (a UDP connect sends no packets)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))     # TEST-NET-1: never routed, only selects the outbound interface
            return s.getsockname()[0]
        except OSError:
            return None


def resolve(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def in_venv() -> tuple[bool, Path]:
    return sys.prefix != sys.base_prefix, Path(sys.prefix)


def this_machine() -> str:
    from controller.feasibility import machine   # the same string `make calibrate` writes

    return machine()


def agent_backend() -> str:
    from agent.llm import get_llm

    llm = get_llm()
    return llm.name if llm.available else "offline"


def now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python(ctx: Ctx) -> list[Check]:
    out = []
    inside, prefix = in_venv()
    want = ctx.root / ".venv"
    if not inside:
        out.append(Check("python env", "FAIL", f"not in a virtualenv ({sys.executable})",
                         "run through uv: `make preflight` or `uv run python scripts/preflight.py`"))
    elif want.exists() and prefix.resolve() == want.resolve():
        out.append(Check("python env", "PASS", f".venv, Python {platform.python_version()}"))
    else:
        out.append(Check("python env", "WARN", f"virtualenv at {prefix}, not ./.venv",
                         "fine if it has the deps; `make setup` builds ./.venv"))
    missing = [m for m in IMPORTS if not has_module(m)]
    out.append(Check("imports", "FAIL" if missing else "PASS",
                     f"missing: {', '.join(missing)}" if missing else f"{len(IMPORTS)} runtime packages import",
                     "make setup" if missing else ""))
    if ctx.is_mac:
        missing = [m for m in MAC_IMPORTS if not has_module(m)]
        out.append(Check("mac extras", "FAIL" if missing else "PASS",
                         f"missing: {', '.join(missing)}" if missing else "torch, sentence-transformers import",
                         "uv pip install -e '.[mac]'" if missing else ""))
    else:
        out.append(Check("mac extras", "SKIP", "not macOS: workloads run on the demo Mac"))
    return out


def check_env(ctx: Ctx) -> list[Check]:
    if not ctx.env_file_exists:
        return [Check(".env", "FAIL", "no .env in the repo root", "cp .env.example .env and fill it in")]
    empty = [k for k in REQUIRED_ENV if not (ctx.env.get(k) or "").strip()]
    out = [Check(".env", "FAIL" if empty else "PASS",
                 f"empty: {', '.join(empty)}" if empty else f"{', '.join(REQUIRED_ENV)} set",
                 "fill these in .env" if empty else "")]
    try:
        backend = agent_backend()
    except Exception as e:  # a broken agent config must not hide the other checks
        out.append(Check("agent backend", "WARN", f"get_llm() raised {type(e).__name__}",
                         "check the agent keys in .env; the demo runs with 'agent offline' without them"))
        return out
    if backend == "offline":
        out.append(Check("agent backend", "WARN", "no agent key or endpoint: dashboard shows 'agent offline'",
                         "set ANTHROPIC_API_KEY + ANTHROPIC_MODEL or AZURE_AI_PROJECT_ENDPOINT in .env"))
    else:
        out.append(Check("agent backend", "PASS", f"get_llm() -> {backend}"))
    return out


def _chat_cfg(ctx: Ctx) -> dict:
    return (ctx.jobs.get("workloads") or {}).get("chat") or {}


def check_ollama(ctx: Ctx) -> list[Check]:
    url = (ctx.env.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
    model = (ctx.env.get("OLLAMA_MODEL") or "").strip()
    try:
        r = http_get(f"{url}/api/tags", timeout=3)
        r.raise_for_status()
        names = {m.get("name", "") for m in r.json().get("models", [])}
    except (httpx.HTTPError, ValueError) as e:
        return [Check("ollama", "FAIL", f"{url} unreachable ({type(e).__name__})",
                      f"start it: OLLAMA_NUM_PARALLEL={ctx.env.get('OLLAMA_NUM_PARALLEL') or 4} ollama serve")]
    out = [Check("ollama", "PASS", f"{url} up, {len(names)} model(s)")]
    if not model:
        out.append(Check("ollama model", "FAIL", "OLLAMA_MODEL is empty", "set OLLAMA_MODEL in .env"))
        return out
    if model not in names and f"{model}:latest" not in names:
        out.append(Check("ollama model", "FAIL", f"{model} not pulled", f"ollama pull {model}"))
        return out
    out.append(Check("ollama model", "PASS", f"{model} pulled"))
    think = bool(_chat_cfg(ctx).get("think", False))
    t0 = now()
    try:
        r = http_post(f"{url}/api/chat", {"model": model, "stream": False, "think": think,
                                          "messages": [{"role": "user", "content": "Reply with OK."}],
                                          "options": {"num_predict": 1}})
        r.raise_for_status()
        msg = r.json().get("message", {})
    except (httpx.HTTPError, ValueError) as e:
        out.append(Check("ollama reasoning", "FAIL", f"1-token probe failed ({type(e).__name__})",
                         f"try `ollama run {model}` by hand"))
        return out
    reasoning = (msg.get("thinking") or "").strip() or ("<think" in (msg.get("content") or ""))
    if reasoning:
        out.append(Check("ollama reasoning", "FAIL", f"{model} returned reasoning text with think={think}",
                         "use a non-thinking build, or set workloads.chat.think: false in config/jobs.yaml"))
    else:
        out.append(Check("ollama reasoning", "PASS", f"1-token probe, no reasoning text, {now() - t0:.1f} s"))
    return out


def check_calibration(ctx: Ctx) -> list[Check]:
    if not ctx.is_mac:
        return [Check("calibration", "SKIP", "not macOS: calibration is measured on the demo Mac")]
    path = ctx.root / (ctx.env.get("CALIBRATION_PATH") or "runs/calibration.json")
    if not path.exists():
        return [Check("calibration", "FAIL", f"{path.relative_to(ctx.root)} missing",
                      "with the Mac otherwise idle: sudo -v && make calibrate")]
    try:
        cal = json.loads(path.read_text())
        measured_at, machine = float(cal["measured_at"]), str(cal["machine"])
    except (ValueError, KeyError, TypeError) as e:
        return [Check("calibration", "FAIL", f"unreadable ({type(e).__name__})", "sudo -v && make calibrate")]
    here = this_machine()
    if machine != here:
        return [Check("calibration", "FAIL", f"measured on '{machine}', this is '{here}'",
                      "recalibrate on this Mac: sudo -v && make calibrate")]
    age_h = (now() - measured_at) / 3600
    if age_h > CALIBRATION_MAX_AGE_H:
        return [Check("calibration", "FAIL", f"{age_h:.1f} h old (limit {CALIBRATION_MAX_AGE_H} h)",
                      "with the Mac otherwise idle: sudo -v && make calibrate")]
    return [Check("calibration", "PASS", f"{machine}, {age_h:.1f} h old")]


def check_ports(ctx: Ctx) -> list[Check]:
    out = []
    host = ctx.env.get("HOST") or "0.0.0.0"
    wanted = [("dashboard port", host, int(ctx.env.get("PORT") or 8080))]
    if (proxy := _chat_cfg(ctx).get("proxy_port")) is not None:
        wanted.append(("chat proxy port", "127.0.0.1", int(proxy)))
    for name, h, p in wanted:
        busy = port_in_use(h, p)
        out.append(Check(name, "FAIL" if busy else "PASS", f":{p} {'in use' if busy else 'free'}",
                         f"something already listens on :{p} (an earlier make demo?): stop it" if busy else ""))
    return out


def _caiso_node(ctx: Ctx) -> str | None:
    if (ctx.env.get("ISO") or "").upper() == "CAISO" and ctx.env.get("LOCATION"):
        return ctx.env["LOCATION"]
    locs = ((ctx.isos.get("isos") or {}).get("CAISO") or {}).get("locations") or []
    return locs[0] if isinstance(locs, list) and locs else None


def check_oasis(ctx: Ctx) -> list[Check]:
    node = _caiso_node(ctx)
    if not node:
        return [Check("CAISO OASIS", "SKIP", "no CAISO location in .env or config/isos.yaml")]
    t1 = datetime.fromtimestamp(now(), timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=15)
    t1 -= timedelta(minutes=t1.minute % 5)
    t0 = t1 - timedelta(minutes=5)
    start = now()
    try:
        r = http_get(OASIS, timeout=30, params={
            "resultformat": 6, "queryname": "PRC_INTVL_LMP", "version": 3, "market_run_id": "RTM", "node": node,
            "startdatetime": t0.strftime("%Y%m%dT%H:%M-0000"), "enddatetime": t1.strftime("%Y%m%dT%H:%M-0000")})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return [Check("CAISO OASIS", "FAIL", f"unreachable ({type(e).__name__})",
                      "check the network; without it the dashboard shows STALE and plans on last known data")]
    took = now() - start
    if not r.content.startswith(b"PK"):
        return [Check("CAISO OASIS", "WARN", f"answered in {took:.1f} s but not with data (rate limit?)",
                      "wait a minute and re-run; OASIS throttles bursts")]
    return [Check("CAISO OASIS", "PASS", f"{node} interval answered in {took:.1f} s")]


SUDO_PM = ["sudo", "-n", "/usr/bin/powermetrics", "--samplers", "cpu_power,gpu_power", "-i", "1000", "-n", "1"]


def check_sudo(ctx: Ctx) -> list[Check]:
    if not ctx.is_mac:
        return [Check("sudo", "SKIP", "not macOS: powermetrics runs on the demo Mac")]
    # The same probe as the Makefile's SUDO_PM: the demo Mac's sudoers rule allows only this exact command line.
    code, _ = run(SUDO_PM)
    return [Check("sudo", "PASS", "powermetrics runs without a prompt")] if code == 0 else \
        [Check("sudo", "FAIL", "powermetrics needs a password in this terminal",
               "run sudo -v in this terminal, then make demo from the same terminal")]


def check_disk(ctx: Ctx) -> list[Check]:
    gb = disk_free_gb(ctx.root)
    if gb < DISK_FAIL_GB:
        return [Check("disk", "FAIL", f"{gb:.1f} GB free", "free space: runs/ and checkpoints/ grow during the demo")]
    if gb < DISK_WARN_GB:
        return [Check("disk", "WARN", f"{gb:.1f} GB free", "clear old runs/ if the demo will be long")]
    return [Check("disk", "PASS", f"{gb:.0f} GB free")]


def _tag_number(tag: str) -> int:
    n = tag.rsplit("-", 1)[-1]
    return int(n) if n.isdigit() else -1


def check_git(ctx: Ctx) -> list[Check]:
    out = []
    code, status = run(["git", "status", "--porcelain"], cwd=ctx.root)
    if code != 0:
        return [Check("git", "FAIL", "not a git checkout", "run from the repo")]
    out.append(Check("git clean", "FAIL" if status else "PASS",
                     f"{len(status.splitlines())} uncommitted change(s)" if status else "working tree clean",
                     "commit or stash: the demo runs from a clean tag" if status else ""))
    code, tag = run(["git", "describe", "--tags", "--exact-match", "--match", "demo-stable-*", "HEAD"], cwd=ctx.root)
    if code == 0:
        out.append(Check("demo tag", "PASS", f"HEAD is {tag}"))
    else:
        _, tags = run(["git", "tag", "-l", "demo-stable-*"], cwd=ctx.root)
        newest = max(tags.split(), key=_tag_number, default="")
        out.append(Check("demo tag", "FAIL",
                         f"HEAD is not at a demo-stable-* tag (newest: {newest})" if newest else
                         "no demo-stable-* tag yet",
                         "tag this commit once the rehearsal passes: make tag-stable"))
    return out


def check_public_url(ctx: Ctx) -> list[Check]:
    url = ctx.env.get("PUBLIC_URL") or ""
    host = urlparse(url).hostname
    if not host:
        return [Check("PUBLIC_URL", "FAIL", f"not a URL: {url!r}", "set PUBLIC_URL=http://<this machine's LAN IP>:<PORT>")]
    lan = lan_ip()
    port = ctx.env.get("PORT") or "8080"
    if lan is None:
        return [Check("PUBLIC_URL", "WARN", "no network interface found to compare against",
                      "connect to the venue network, then re-run")]
    ip = resolve(host)
    if ip != lan:
        return [Check("PUBLIC_URL", "FAIL", f"host {host} ({ip}) is not this machine's LAN IP {lan}",
                      f"set PUBLIC_URL=http://{lan}:{port} and re-run make qr")]
    return [Check("PUBLIC_URL", "PASS", f"{host} is this machine ({lan})")]


CHECKS = [check_python, check_env, check_ollama, check_calibration, check_ports, check_oasis, check_sudo,
          check_disk, check_git, check_public_url]


def context(root: Path = ROOT) -> Ctx:
    env_path = root / ".env"
    load = lambda p: yaml.safe_load(p.read_text()) if p.exists() else {}
    env = {k: v or "" for k, v in dotenv_values(env_path).items()} if env_path.exists() else {}
    return Ctx(root=root, env=env, jobs=load(root / "config" / "jobs.yaml"), isos=load(root / "config" / "isos.yaml"),
               is_mac=platform.system() == "Darwin", env_file_exists=env_path.exists())


def preflight(ctx: Ctx) -> list[Check]:
    results: list[Check] = []
    for check in CHECKS:
        results += check(ctx)
    return results


def report(results: list[Check]) -> str:
    width = max(len(c.name) for c in results)
    lines = []
    for c in results:
        lines.append(f"{c.status:<5} {c.name:<{width}}  {c.detail}")
        if c.fix and c.status in ("FAIL", "WARN"):
            lines.append(f"{'':<5} {'':<{width}}  -> {c.fix}")
    counts = {s: sum(c.status == s for c in results) for s in ("PASS", "WARN", "FAIL", "SKIP")}
    lines.append("")
    lines.append(", ".join(f"{n} {s}" for s, n in counts.items()) +
                 ("  => NOT READY" if counts["FAIL"] else "  => ready"))
    return "\n".join(lines)


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))   # agent/ and controller/ when run as a plain script
    results = preflight(context())
    print(report(results))
    return 1 if any(c.status == "FAIL" for c in results) else 0


if __name__ == "__main__":
    sys.exit(main())
