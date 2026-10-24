"""telemetry/: spans made by any module land in the ring buffer; Azure Monitor is attached only
when a connection string is set."""
import pytest
from opentelemetry import trace

import telemetry


def test_spans_reach_recent_spans(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    sinks = telemetry.configure()
    assert sinks[0] == "memory"
    assert telemetry.configure() == sinks                 # idempotent
    tracer = trace.get_tracer("brownout.agent")
    with tracer.start_as_current_span("negotiate") as parent:
        parent.set_attribute("job_id", "train")
        with tracer.start_as_current_span("llm.call") as child:
            child.set_attribute("model", "test-model")
            child.add_event("reply", {"decision": "refuse"})
    spans = telemetry.recent_spans(2)
    assert [s["name"] for s in spans] == ["llm.call", "negotiate"]   # children end first
    child, parent = spans
    assert child["trace_id"] == parent["trace_id"]
    assert child["parent_id"] == parent["span_id"]
    assert parent["attributes"] == {"job_id": "train"}
    assert child["events"][0]["attributes"] == {"decision": "refuse"}
    assert child["duration_ms"] >= 0 and child["status"] == "UNSET"
    assert telemetry.recent_spans(0) == []
    assert telemetry.flush()


def test_azure_processor_builds_exporter():
    pytest.importorskip("azure.monitor.opentelemetry.exporter")
    # A syntactically valid connection string; constructing the exporter makes no network call.
    p = telemetry.azure_processor("InstrumentationKey=00000000-0000-0000-0000-000000000000;"
                                  "IngestionEndpoint=https://westus2-0.in.applicationinsights.azure.com/")
    assert type(p.span_exporter).__name__ == "AzureMonitorTraceExporter"
    p.shutdown()
