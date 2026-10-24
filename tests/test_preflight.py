"""scripts/preflight.py logic with its probes replaced (test doubles live here, never in the script)."""
import importlib.util
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
pf = importlib.util.module_from_spec(_spec)
sys.modules["preflight"] = pf          # dataclasses resolve their module through sys.modules
_spec.loader.exec_module(pf)

FULL_ENV = {"ISO": "CAISO", "LOCATION": "TH_SP15_GEN-APND", "OLLAMA_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "qwen3:4b", "PUBLIC_URL": "http://192.168.1.10:8080", "PORT": "8080",
            "ANTHROPIC_API_KEY": "sk-ant-test-secret-value", "ANTHROPIC_MODEL": "claude-sonnet-5-5"}
JOBS = {"workloads": {"chat": {"proxy_port": 8090, "think": False}}}


def ctx(tmp_path, env=None, mac=False, env_file=True):
    return pf.Ctx(root=tmp_path, env=dict(FULL_ENV if env is None else env), jobs=JOBS,
                  isos={"isos": {"CAISO": {"locations": ["TH_SP15_GEN-APND"]}}}, is_mac=mac, env_file_exists=env_file)


def resp(status=200, json_body=None, content=None, url="http://x"):
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=httpx.Request("GET", url))
    return httpx.Response(status, content=content or b"", request=httpx.Request("GET", url))


def statuses(checks):
    return {c.name: c.status for c in checks}


# ---------- platform ----------

def test_mac_only_checks_skip_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "has_module", lambda m: True)
    c = ctx(tmp_path, mac=False)
    assert statuses(pf.check_python(c))["mac extras"] == "SKIP"
    assert pf.check_calibration(c)[0].status == "SKIP"
    assert pf.check_sudo(c)[0].status == "SKIP"


def test_missing_imports_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "has_module", lambda m: m != "ortools")
    imports = next(c for c in pf.check_python(ctx(tmp_path)) if c.name == "imports")
    assert imports.status == "FAIL" and "ortools" in imports.detail


# ---------- .env and the agent backend ----------

def test_env_missing_file_and_empty_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "agent_backend", lambda: "offline")
    assert pf.check_env(ctx(tmp_path, env_file=False))[0].status == "FAIL"
    checks = pf.check_env(ctx(tmp_path, env={**FULL_ENV, "OLLAMA_MODEL": "", "PUBLIC_URL": " "}))
    assert checks[0].status == "FAIL" and "OLLAMA_MODEL" in checks[0].detail and "PUBLIC_URL" in checks[0].detail


def test_agent_backend_reported_without_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "agent_backend", lambda: "claude:claude-sonnet-5-5")
    checks = pf.check_env(ctx(tmp_path))
    assert statuses(checks) == {".env": "PASS", "agent backend": "PASS"}
    assert FULL_ENV["ANTHROPIC_API_KEY"] not in pf.report(checks)
    monkeypatch.setattr(pf, "agent_backend", lambda: "offline")
    assert pf.check_env(ctx(tmp_path))[1].status == "WARN"


# ---------- Ollama ----------

def test_ollama_unreachable(tmp_path, monkeypatch):
    def down(url, params=None, timeout=5.0):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(pf, "http_get", down)
    checks = pf.check_ollama(ctx(tmp_path))
    assert checks[0].status == "FAIL" and "ollama serve" in checks[0].fix


def test_ollama_model_not_pulled(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "http_get", lambda url, params=None, timeout=5.0: resp(json_body={"models": []}))
    checks = pf.check_ollama(ctx(tmp_path))
    assert statuses(checks)["ollama model"] == "FAIL" and checks[-1].fix == "ollama pull qwen3:4b"


@pytest.mark.parametrize("message,expected", [
    ({"content": "OK"}, "PASS"),
    ({"content": "", "thinking": "Okay, the user wants"}, "FAIL"),
    ({"content": "<think>"}, "FAIL"),
])
def test_ollama_reasoning_probe(tmp_path, monkeypatch, message, expected):
    monkeypatch.setattr(pf, "http_get",
                        lambda url, params=None, timeout=5.0: resp(json_body={"models": [{"name": "qwen3:4b"}]}))
    sent = {}

    def post(url, payload, timeout=60.0):
        sent.update(payload)
        return resp(json_body={"message": message})
    monkeypatch.setattr(pf, "http_post", post)
    checks = pf.check_ollama(ctx(tmp_path))
    assert statuses(checks)["ollama reasoning"] == expected
    assert sent["options"] == {"num_predict": 1} and sent["think"] is False   # think follows config/jobs.yaml


# ---------- calibration (macOS) ----------

def write_cal(tmp_path, machine="Apple M2 Pro macOS 15.4.1", age_h=1.0):
    (tmp_path / "runs").mkdir(exist_ok=True)
    (tmp_path / "runs" / "calibration.json").write_text(
        json.dumps({"measured_at": time.time() - age_h * 3600, "machine": machine}))


def test_calibration_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "this_machine", lambda: "Apple M2 Pro macOS 15.4.1")
    c = ctx(tmp_path, mac=True)
    assert pf.check_calibration(c)[0].status == "FAIL"                      # missing
    write_cal(tmp_path, machine="Apple M1 macOS 14.0")
    assert "measured on" in pf.check_calibration(c)[0].detail               # another machine
    write_cal(tmp_path, age_h=13)
    assert "h old" in pf.check_calibration(c)[0].detail and pf.check_calibration(c)[0].status == "FAIL"
    write_cal(tmp_path, age_h=2)
    assert pf.check_calibration(c)[0].status == "PASS"


# ---------- ports, OASIS, sudo, disk ----------

def test_busy_port_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "port_in_use", lambda host, port: port == 8090)
    assert statuses(pf.check_ports(ctx(tmp_path))) == {"dashboard port": "PASS", "chat proxy port": "FAIL"}


@pytest.mark.parametrize("outcome,expected", [(b"PK\x03\x04zip", "PASS"), (b"<xml>rate limited</xml>", "WARN"),
                                              (None, "FAIL")])
def test_oasis(tmp_path, monkeypatch, outcome, expected):
    def get(url, params=None, timeout=5.0):
        if outcome is None:
            raise httpx.ConnectTimeout("no network")
        assert params["node"] == "TH_SP15_GEN-APND"
        return resp(content=outcome)
    monkeypatch.setattr(pf, "http_get", get)
    assert pf.check_oasis(ctx(tmp_path))[0].status == expected


def test_sudo_on_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "run", lambda cmd, cwd=None: (0, ""))
    assert pf.check_sudo(ctx(tmp_path, mac=True))[0].status == "PASS"
    monkeypatch.setattr(pf, "run", lambda cmd, cwd=None: (1, "a password is required"))
    assert "sudo -v" in pf.check_sudo(ctx(tmp_path, mac=True))[0].fix


@pytest.mark.parametrize("gb,expected", [(1.0, "FAIL"), (5.0, "WARN"), (50.0, "PASS")])
def test_disk(tmp_path, monkeypatch, gb, expected):
    monkeypatch.setattr(pf, "disk_free_gb", lambda p: gb)
    assert pf.check_disk(ctx(tmp_path))[0].status == expected


# ---------- git ----------

def git_runner(status="", tag=None, tags=""):
    def run(cmd, cwd=None):
        if cmd[1] == "status":
            return 0, status
        if cmd[1] == "describe":
            return (0, tag) if tag else (128, "fatal: no tag exactly matches")
        return 0, tags
    return run


def test_git_clean_at_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "run", git_runner(tag="demo-stable-3"))
    assert statuses(pf.check_git(ctx(tmp_path))) == {"git clean": "PASS", "demo tag": "PASS"}


def test_git_dirty_and_off_tag_points_at_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "run", git_runner(status=" M web/app.js", tags="demo-stable-2\ndemo-stable-10\n"))
    checks = pf.check_git(ctx(tmp_path))
    assert statuses(checks) == {"git clean": "FAIL", "demo tag": "FAIL"}
    assert checks[1].fix == "git checkout demo-stable-10"


def test_git_no_tags_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "run", git_runner())
    assert "make tag-stable" in pf.check_git(ctx(tmp_path))[1].fix


# ---------- PUBLIC_URL ----------

def test_public_url(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "lan_ip", lambda: "192.168.1.10")
    monkeypatch.setattr(pf, "resolve", lambda host: {"192.168.1.10": "192.168.1.10",
                                                     "localhost": "127.0.0.1"}.get(host))
    assert pf.check_public_url(ctx(tmp_path))[0].status == "PASS"
    bad = pf.check_public_url(ctx(tmp_path, env={**FULL_ENV, "PUBLIC_URL": "http://localhost:8080"}))[0]
    assert bad.status == "FAIL" and bad.fix.startswith("set PUBLIC_URL=http://192.168.1.10:8080")
    assert pf.check_public_url(ctx(tmp_path, env={**FULL_ENV, "PUBLIC_URL": ""}))[0].status == "FAIL"


# ---------- exit code ----------

def test_exit_code_follows_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "context", lambda root=None: ctx(tmp_path))
    monkeypatch.setattr(pf, "CHECKS", [lambda c: [pf.Check("a", "PASS", "ok"), pf.Check("b", "SKIP", "n/a"),
                                                  pf.Check("c", "WARN", "meh", "fix it")]])
    assert pf.main() == 0
    monkeypatch.setattr(pf, "CHECKS", [lambda c: [pf.Check("a", "FAIL", "broken", "do this")]])
    assert pf.main() == 1
    assert "-> do this" in pf.report([pf.Check("a", "FAIL", "broken", "do this")])
