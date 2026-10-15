"""OpenTelemetry setup. Off unless configured, so nothing is sent anywhere by default.

  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   export OTLP/HTTP spans to any collector
                                                      (Phoenix, Langfuse, Jaeger, Tempo, ...)
  PAGEINDEX_OTEL_CONSOLE=1                            print spans to stdout (debugging)

Spans: one `pageindex.question` span per question (collection, cost, tool calls),
with LangChain/LangGraph model and tool spans nested under it (OpenInference).
"""

from __future__ import annotations

import os

_configured = False


def setup_tracing(service_name: str = "pageindex-rag") -> bool:
    global _configured
    if _configured:
        return True
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    console = os.getenv("PAGEINDEX_OTEL_CONSOLE") == "1"
    if not endpoint and not console:
        return False

    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads OTEL_* env vars
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    _configured = True
    return True
