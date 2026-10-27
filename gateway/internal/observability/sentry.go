// Package observability wires Sentry (error monitoring + tracing + logs) into
// the gateway. It is intentionally optional: with an empty DSN the SDK is a
// no-op and the gateway logs exactly as before.
package observability

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/getsentry/sentry-go"
	sentryotel "github.com/getsentry/sentry-go/otel"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// sensitiveQueryParams are stripped from captured request query strings. The
// gateway no longer reads ?token=, but older WebSocket clients may still send
// one and sentryhttp records the raw query string regardless of SendDefaultPII,
// so scrub these defensively for every event.
var sensitiveQueryParams = map[string]struct{}{
	"token":         {},
	"access_token":  {},
	"refresh_token": {},
	"api_key":       {},
}

// Init initialises the Sentry SDK from config. With an empty DSN sentry.Init is
// a no-op (the SDK stays disabled) and the returned flush is a no-op too, so the
// gateway is unaffected. The caller should defer the returned flush so buffered
// events are delivered on shutdown.
func Init(cfg *config.Config) (func(time.Duration), error) {
	err := sentry.Init(sentry.ClientOptions{
		Dsn:              cfg.Sentry.DSN,
		Environment:      cfg.Sentry.Environment,
		Release:          cfg.Sentry.Release,
		AttachStacktrace: true,
		// The gateway forwards JWTs in Authorization headers and cookies; keeping
		// SendDefaultPII off leaves those (and client IPs) out of captured events.
		SendDefaultPII: false,
		// Spans come from OpenTelemetry (internal/tracing) and reach Sentry through
		// the otel-collector's Sentry Exporter, so this SDK ships no transactions
		// of its own by default (SENTRY_TRACES_SAMPLE_RATE=0). The OTel integration
		// is pure linking: it resolves an event's trace context from the active
		// OTel span so an Issue opens on the same trace Grafana shows.
		Integrations: func(i []sentry.Integration) []sentry.Integration {
			return append(i, sentryotel.NewOtelIntegration())
		},
		EnableTracing:    cfg.Sentry.TracesSampleRate > 0,
		TracesSampleRate: cfg.Sentry.TracesSampleRate,
		// QueryString is recorded verbatim regardless of SendDefaultPII; scrub the
		// JWT (and similar) out of both error and transaction events.
		BeforeSend: func(event *sentry.Event, hint *sentry.EventHint) *sentry.Event {
			if isClientDisconnect(hint) {
				return nil
			}
			return scrubEvent(event)
		},
		BeforeSendTransaction: func(event *sentry.Event, _ *sentry.EventHint) *sentry.Event {
			return scrubEvent(event)
		},
	})
	if err != nil {
		return func(time.Duration) {}, fmt.Errorf("sentry init: %w", err)
	}
	return func(d time.Duration) { sentry.Flush(d) }, nil
}

// isClientDisconnect reports whether a captured event is a client hanging up
// rather than a gateway fault.
//
// httputil.ReverseProxy panics with http.ErrAbortHandler when the response copy
// to the client fails mid-body (navigation away, closed tab, a scanner probing
// the public IP and dropping the socket). sentryhttp runs with Repanic: true, so
// net/http's recover turns every one of those into a *fatal* Sentry event under
// "net/http: abort Handler" — by volume the loudest issue in the project and
// never once actionable. context.Canceled/DeadlineExceeded reach CaptureException
// the same way via safego.
func isClientDisconnect(hint *sentry.EventHint) bool {
	if hint == nil {
		return false
	}
	candidates := []error{hint.OriginalException}
	if err, ok := hint.RecoveredException.(error); ok {
		candidates = append(candidates, err)
	}
	for _, err := range candidates {
		if err == nil {
			continue
		}
		if errors.Is(err, http.ErrAbortHandler) ||
			errors.Is(err, context.Canceled) ||
			errors.Is(err, context.DeadlineExceeded) {
			return true
		}
	}
	return false
}

// scrubEvent redacts sensitive query parameters from a captured event's request.
func scrubEvent(event *sentry.Event) *sentry.Event {
	if event != nil && event.Request != nil && event.Request.QueryString != "" {
		event.Request.QueryString = redactQuery(event.Request.QueryString)
	}
	return event
}

// redactQuery replaces the values of sensitive query parameters with a marker.
// An unparseable query string is dropped entirely rather than risk leaking it.
func redactQuery(raw string) string {
	values, err := url.ParseQuery(raw)
	if err != nil {
		return "[redacted]"
	}
	for key := range values {
		if _, ok := sensitiveQueryParams[strings.ToLower(key)]; ok {
			values.Set(key, "[redacted]")
		}
	}
	return values.Encode()
}
