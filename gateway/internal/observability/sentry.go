// Package observability wires Sentry (error monitoring + tracing + logs) into
// the gateway. It is intentionally optional: with an empty DSN the SDK is a
// no-op and the gateway logs exactly as before.
package observability

import (
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/getsentry/sentry-go"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// sensitiveQueryParams are stripped from captured request query strings. The WS
// endpoint accepts the JWT via ?token=; sentryhttp records the raw query string
// regardless of SendDefaultPII, so scrub these defensively for every event.
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
		SendDefaultPII:   false,
		EnableTracing:    cfg.Sentry.TracesSampleRate > 0,
		TracesSampleRate: cfg.Sentry.TracesSampleRate,
		// QueryString is recorded verbatim regardless of SendDefaultPII; scrub the
		// JWT (and similar) out of both error and transaction events.
		BeforeSend: func(event *sentry.Event, _ *sentry.EventHint) *sentry.Event {
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
