"""Chat service: FastAPI in front of Ollama. Our limiter is the concurrency knob (Ollama's
OLLAMA_NUM_PARALLEL is fixed at server start); `max_tokens` is the degrade knob. Every request's
latency is recorded; p95 over the last 60 s is in /status and the status file.

    uv run python -m workloads.chat_proxy     # serves on workloads.chat.proxy_port
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import time
from collections import deque

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.config import settings

from .base import WL, control_path, read_json, status_path, write_json

CFG = WL.get("chat", {})


class Limiter:
    """A semaphore whose limit can change at runtime. 0 = paused (requests wait)."""

    def __init__(self, limit: int):
        self.limit, self.inflight = limit, 0
        self.cond = asyncio.Condition()

    async def set(self, n: int):
        async with self.cond:
            self.limit = n
            self.cond.notify_all()

    async def __aenter__(self):
        async with self.cond:
            await self.cond.wait_for(lambda: self.inflight < self.limit)
            self.inflight += 1

    async def __aexit__(self, *exc):
        async with self.cond:
            self.inflight -= 1
            self.cond.notify_all()


def p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


class ChatIn(BaseModel):
    messages: list[dict]
    max_tokens: int | None = None


class ChatError(Exception):
    pass


def make_app(max_concurrency: int, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    lim = Limiter(max_concurrency)
    lat: deque[tuple[float, float, float]] = deque(maxlen=5000)   # (t, total_s, ttft_s)
    state = {"max_tokens": CFG.get("max_tokens", 256), "served": 0, "errors": 0}
    client = httpx.AsyncClient(base_url=settings.ollama_url, timeout=120, transport=transport)

    def snapshot() -> dict:
        now = time.time()
        recent = [(l, f) for t, l, f in lat if now - t <= 60]
        return {"job": "chat", "state": "running" if lim.limit > 0 else "paused", "device": "gpu",
                "concurrency": lim.limit, "inflight": lim.inflight, "max_tokens": state["max_tokens"],
                "p95_60s": p95([l for l, _ in recent]), "ttft_p95_60s": p95([f for _, f in recent]),
                "n_60s": len(recent), "served": state["served"],
                "errors": state["errors"], "model": settings.ollama_model, "t": now}

    async def follow_control():
        # knobs write runs/control/chat.json; apply changes within ~250 ms. Exit if the runtime died.
        parent = os.getppid()
        while True:
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGTERM)
            c = read_json(control_path("chat"))
            if "concurrency" in c and int(c["concurrency"]) != lim.limit:
                await lim.set(int(c["concurrency"]))
            if "max_tokens" in c:
                state["max_tokens"] = int(c["max_tokens"])
            write_json(status_path("chat"), snapshot())
            await asyncio.sleep(0.25)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(follow_control())
        yield
        task.cancel()

    app = FastAPI(title="brownout chat proxy", lifespan=lifespan)

    async def generate(body: ChatIn):
        """Yields {"delta": text} as Ollama produces it, then one {"done": true, ...stats}. Holds a
        concurrency slot until the last token; TTFT and total include time queued for the slot."""
        t0 = time.time()
        ttft, tokens = None, None
        async with lim:
            n = min(body.max_tokens or state["max_tokens"], state["max_tokens"])
            try:
                async with client.stream("POST", "/api/chat", json={
                        "model": settings.ollama_model, "messages": body.messages, "stream": True,
                        "think": CFG.get("think", False), "options": {"num_predict": n}}) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        d = json.loads(line)
                        piece = d.get("message", {}).get("content", "")
                        if piece:
                            if ttft is None:
                                ttft = time.time() - t0
                            yield {"delta": piece}
                        if d.get("done"):
                            tokens = d.get("eval_count")
            except httpx.HTTPError as e:
                state["errors"] += 1
                raise ChatError(f"ollama: {e!r}") from e
        dt = time.time() - t0
        ttft = dt if ttft is None else ttft
        lat.append((time.time(), dt, ttft))
        state["served"] += 1
        yield {"done": True, "latency_s": round(dt, 3), "ttft_s": round(ttft, 3), "tokens": tokens, "max_tokens": n}

    @app.post("/chat")
    async def chat(body: ChatIn):
        parts, final = [], {}
        try:
            async for ev in generate(body):
                if "delta" in ev:
                    parts.append(ev["delta"])
                else:
                    final = ev
        except ChatError as e:
            raise HTTPException(502, str(e))
        final.pop("done", None)
        return {"reply": "".join(parts), **final}

    @app.post("/chat/stream")
    async def chat_stream(body: ChatIn):
        async def ndjson():
            try:
                async for ev in generate(body):
                    yield json.dumps(ev) + "\n"
            except ChatError as e:
                yield json.dumps({"error": str(e)}) + "\n"
        return StreamingResponse(ndjson(), media_type="application/x-ndjson")

    @app.get("/status")
    async def status():
        return snapshot()

    return app


if __name__ == "__main__":
    from core.config import jobs
    chat_job = next(j for j in jobs["jobs"] if j["id"] == "chat")
    uvicorn.run(make_app(chat_job["max_concurrency"]), host="127.0.0.1", port=CFG["proxy_port"], log_level="warning")
