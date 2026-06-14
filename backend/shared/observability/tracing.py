"""OpenTelemetry distributed tracing setup."""

from __future__ import annotations

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBasedTraceIdRatio


def _build_sampler(sampler_name: str, sampler_arg: float):
    sampler_key = sampler_name.lower()
    if sampler_key == "always_on":
        return ALWAYS_ON
    if sampler_key == "always_off":
        return ALWAYS_OFF
    if sampler_key == "parentbased_traceidratio":
        return ParentBasedTraceIdRatio(sampler_arg)

    logger.warning(f"Unknown OTEL sampler '{sampler_name}', using parentbased_traceidratio")
    return ParentBasedTraceIdRatio(sampler_arg)


def setup_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
    enabled: bool = True,
    sampler_name: str = "parentbased_traceidratio",
    sampler_arg: float = 0.1,
) -> None:
    """Configure OpenTelemetry with an OTLP exporter."""
    if not enabled:
        logger.info("OpenTelemetry tracing disabled")
        return

    if not otlp_endpoint:
        logger.warning("OTLP endpoint not configured, tracing disabled")
        return

    try:
        current_provider = trace.get_tracer_provider()
        if not isinstance(current_provider, TracerProvider):
            provider = TracerProvider(
                resource=Resource(attributes={SERVICE_NAME: service_name}),
                sampler=_build_sampler(sampler_name, sampler_arg),
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
            )
            trace.set_tracer_provider(provider)

        if not getattr(HTTPXClientInstrumentor, "_is_instrumented_by_opentelemetry", False):
            HTTPXClientInstrumentor().instrument()

        logger.success(
            f"Tracing enabled for {service_name} (endpoint={otlp_endpoint}, sampler={sampler_name}:{sampler_arg})"
        )
    except Exception as exc:
        logger.error(f"Failed to setup OpenTelemetry: {exc}")


def instrument_fastapi(app) -> None:
    """Instrument a FastAPI app for automatic tracing."""
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("FastAPI instrumented for tracing")
    except Exception as exc:
        logger.error(f"Failed to instrument FastAPI: {exc}")


def instrument_sqlalchemy(engine) -> None:
    """Instrument a SQLAlchemy engine for automatic query tracing."""
    try:
        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.debug("SQLAlchemy instrumented for tracing")
    except Exception as exc:
        logger.error(f"Failed to instrument SQLAlchemy: {exc}")
