"""Chat proxy streaming and latency accounting. TEST FIXTURE: Ollama is replaced by an httpx
MockTransport that returns a recorded-shape NDJSON stream; the real proxy talks to Ollama."""
import json

import httpx
from fastapi.testclient import TestClient

from workloads.chat_proxy import make_app

STREAM = "\n".join(json.dumps(x) for x in [
    {"message": {"content": "Mid"}, "done": False},
    {"message": {"content": "day solar."}, "done": False},
    {"message": {"content": ""}, "done": True, "eval_count": 3},
]) + "\n"


def app(status=200):
    seen = []

    def handler(req: httpx.Request):
        seen.append(json.loads(req.content))
        return httpx.Response(status, text=STREAM if status == 200 else "boom")
    return TestClient(make_app(4, transport=httpx.MockTransport(handler))), seen


def test_chat_collects_stream_and_reports_ttft():
    c, seen = app()
    r = c.post("/chat", json={"messages": [{"role": "user", "content": "why cheap at noon?"}], "max_tokens": 64}).json()
    assert r["reply"] == "Midday solar." and r["tokens"] == 3 and r["max_tokens"] == 64
    assert 0 <= r["ttft_s"] <= r["latency_s"]
    assert seen[0]["stream"] is True and seen[0]["options"]["num_predict"] == 64
    s = c.get("/status").json()
    assert s["served"] == 1 and s["ttft_p95_60s"] is not None and s["n_60s"] == 1


def test_stream_endpoint_yields_deltas_then_stats():
    c, _ = app()
    lines = [json.loads(l) for l in c.post("/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]}).text.splitlines()]
    assert [l["delta"] for l in lines[:-1]] == ["Mid", "day solar."]
    assert lines[-1]["done"] is True and "ttft_s" in lines[-1]


def test_max_tokens_clamped_to_degrade_knob():
    c, seen = app()
    c.post("/chat", json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10_000})
    assert seen[0]["options"]["num_predict"] <= 256


def test_ollama_error_is_reported_not_hidden():
    c, _ = app(status=500)
    assert c.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 502
    lines = c.post("/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]}).text.splitlines()
    assert "error" in json.loads(lines[-1])
