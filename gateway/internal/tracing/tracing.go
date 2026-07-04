// Package tracing wires OpenTelemetry into the gateway: an OTLP gRPC exporter
// to the shared otel-collector, a parent-based ratio sampler, and W3C
// traceparent propagation. It mirrors the Python side
// (backend/shared/observability/tracing.py) so gateway spans join the same
// distributed traces the FastStream services already emit into Tempo.
//
// When tracing is disabled, Init leaves the global no-op providers in place:
// span starts are free, Inject writes nothing, and SpanContextFromContext is
// invalid — every call site degrades gracefully without flag checks.
package tracing

import (
	"context"
	"fmt"
	"log/slog"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// Init configures the global OpenTelemetry tracer provider and propagator.
// The returned shutdown function flushes buffered spans; it is safe to call
// even when tracing is disabled.
func Init(ctx context.Context, cfg config.Tracing, release, environment string, log *slog.Logger) (func(context.Context) error, error) {
	noop := func(context.Context) error { return nil }
	if !cfg.Enabled || cfg.OTLPEndpoint == "" {
		return noop, nil
	}

	// The dial is lazy/non-blocking: an unreachable collector never blocks
	// startup, spans are dropped until it comes up. WithEndpointURL derives
	// the insecure transport from the http:// scheme (matches the Python
	// exporter's insecure=True).
	exporter, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpointURL(cfg.OTLPEndpoint))
	if err != nil {
		return noop, fmt.Errorf("create otlp trace exporter: %w", err)
	}

	attrs := []resource.Option{
		resource.WithAttributes(
			semconv.ServiceName("gateway"),
			semconv.DeploymentEnvironment(environment),
		),
	}
	if release != "" {
		attrs = append(attrs, resource.WithAttributes(semconv.ServiceVersion(release)))
	}
	res, err := resource.New(ctx, attrs...)
	if err != nil {
		return noop, fmt.Errorf("build otel resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		// Same sampling policy as the Python services: honor the parent's
		// decision, otherwise sample SamplerArg of the traffic. The gateway is
		// the trace root for edge requests, so this decides the whole trace.
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(cfg.SamplerArg))),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	log.Info("tracing enabled", "endpoint", cfg.OTLPEndpoint, "sampler_arg", cfg.SamplerArg)
	return tp.Shutdown, nil
}
