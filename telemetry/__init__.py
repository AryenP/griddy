"""OpenTelemetry setup: the audit log of every decision.

`configure()` once at startup (machine 1 calls it from the API). Spans are created elsewhere with
`opentelemetry.trace.get_tracer("brownout.agent")`; this module only decides where they go:
  - always: an in-memory ring buffer, read by `recent_spans(n)` (served at /api/trace);
  - when APPLICATIONINSIGHTS_CONNECTION_STRING is set and the `[azure]` extra is installed:
    Azure Monitor (Application Insights). Without the extra the ring buffer still works and
    `configure()` says the exporter is missing; it never fails startup.
"""
from __future__ import annotations

import logging
import os
import threading
from collections import deque

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "brownout")
BUFFER_SIZE = int(os.getenv("TRACE_BUFFER_SPANS", "500"))

log = logging.getLogger("telemetry")
_lock = threading.Lock()
_buffer: deque[dict] = deque(maxlen=BUFFER_SIZE)
_configured: list[str] = []


def _span_dict(s: ReadableSpan) -> dict:
    ctx = s.get_span_context()
    return {
        "name": s.name,
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
        "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
        "start": s.start_time / 1e9 if s.start_time else None,
        "end": s.end_time / 1e9 if s.end_time else None,
        "duration_ms": (s.end_time - s.start_time) / 1e6 if s.start_time and s.end_time else None,
        "status": s.status.status_code.name,
        "attributes": dict(s.attributes or {}),
        "events": [{"name": e.name, "t": e.timestamp / 1e9, "attributes": dict(e.attributes or {})}
                   for e in s.events],
    }


class RingBufferProcessor(SpanProcessor):
    """Keeps the most recent finished spans in memory as plain dicts."""

    def on_end(self, span: ReadableSpan) -> None:
        with _lock:
            _buffer.append(_span_dict(span))


def azure_processor(connection_string: str) -> BatchSpanProcessor | None:
    """The Application Insights exporter, or None when the `[azure]` extra is not installed."""
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    except ImportError:
        return None
    return BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=connection_string))


def configure() -> list[str]:
    """Attach the sinks to the process's tracer provider (once per process). Returns the active sinks,
    e.g. ["memory"] or ["memory", "azure-monitor"]; "azure-monitor unavailable" when a connection
    string is set but the exporter is not installed. Reuses an SDK provider someone already installed
    (OpenTelemetry allows only one per process), else installs one."""
    with _lock:
        if _configured:
            return list(_configured)
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
            trace.set_tracer_provider(provider)
        provider.add_span_processor(RingBufferProcessor())
        sinks = ["memory"]
        conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
        if conn:
            proc = azure_processor(conn)
            if proc is None:
                log.warning("APPLICATIONINSIGHTS_CONNECTION_STRING is set but the Azure exporter is not "
                            "installed (uv pip install -e '.[azure]'); spans stay in memory only")
                sinks.append("azure-monitor unavailable")
            else:
                provider.add_span_processor(proc)
                sinks.append("azure-monitor")
        _configured.extend(sinks)
        return sinks


def recent_spans(n: int = 50) -> list[dict]:
    """The newest n finished spans, oldest first."""
    with _lock:
        return list(_buffer)[-n:] if n > 0 else []


def flush(timeout_ms: int = 5000) -> bool:
    """Push buffered spans to every exporter now (call before exit so the last decision reaches Azure)."""
    provider = trace.get_tracer_provider()
    return provider.force_flush(timeout_ms) if isinstance(provider, TracerProvider) else True
