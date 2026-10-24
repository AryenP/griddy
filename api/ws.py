"""One WebSocket, `/ws`: a snapshot on connect, then every timeline event as it is logged.
Timeline callbacks can come from worker threads, so events cross into the loop thread-safely."""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect

from core.timeline import Timeline
from core.types import TimelineEvent


class Broadcaster:
    def __init__(self, tl: Timeline, loop: asyncio.AbstractEventLoop, maxsize: int = 2000):
        self.loop, self.maxsize = loop, maxsize
        self.clients: set[asyncio.Queue] = set()
        tl.subscribe(self._on_event)

    def _on_event(self, ev: TimelineEvent) -> None:
        msg = ev.model_dump_json()
        self.loop.call_soon_threadsafe(self._fanout, msg)

    def _fanout(self, msg: str) -> None:
        for q in list(self.clients):
            if q.full():            # slow client: drop its oldest message, keep the stream live
                q.get_nowait()
            q.put_nowait(msg)

    async def serve(self, ws: WebSocket, snapshot: dict) -> None:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(self.maxsize)
        self.clients.add(q)
        try:
            await ws.send_text(json.dumps({"kind": "snapshot", "data": snapshot}))
            while True:
                await ws.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            self.clients.discard(q)
