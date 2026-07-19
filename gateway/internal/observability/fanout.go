package observability

import (
	"context"
	"errors"
	"log/slog"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
)

// fanoutHandler dispatches each slog record to several underlying handlers.
// It lets the gateway keep writing JSON logs to stdout (the container log)
// while also shipping the same records to Sentry, without an external slog
// multiplexer dependency.
type fanoutHandler struct {
	handlers []slog.Handler
}

// newFanout returns a slog.Handler that forwards to every handler given.
func newFanout(handlers ...slog.Handler) slog.Handler {
	return &fanoutHandler{handlers: handlers}
}

func (h *fanoutHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, sub := range h.handlers {
		if sub.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

func (h *fanoutHandler) Handle(ctx context.Context, record slog.Record) error {
	var errs []error
	for _, sub := range h.handlers {
		if !sub.Enabled(ctx, record.Level) {
			continue
		}
		// Clone so a handler that retains or mutates the record cannot affect
		// the copy passed to the next handler.
		if err := sub.Handle(ctx, record.Clone()); err != nil {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

func (h *fanoutHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	subs := make([]slog.Handler, len(h.handlers))
	for i, sub := range h.handlers {
		subs[i] = sub.WithAttrs(attrs)
	}
	return &fanoutHandler{handlers: subs}
}

func (h *fanoutHandler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	subs := make([]slog.Handler, len(h.handlers))
	for i, sub := range h.handlers {
		subs[i] = sub.WithGroup(name)
	}
	return &fanoutHandler{handlers: subs}
}

// accessLogFilter wraps the Sentry slog.Handler and drops any record tagging
// itself as an access log (httplog.AccessLogAttr). The per-request access log is
// operational telemetry already shipped to stdout/Loki: as a Sentry Issue every
// edge 5xx — including internet vuln-scanner probes against the public IP —
// would open a noise issue grouped under "request completed", and as a Sentry
// Log it would flood ingest at edge throughput. Genuine faults are logged
// elsewhere (panics via sentryhttp, explicit .Error() calls) without the attr,
// so they still reach Sentry. Only stdout/Loki keeps the access log.
type accessLogFilter struct {
	inner slog.Handler
}

// dropAccessLogs wraps inner so access-log records never reach it.
func dropAccessLogs(inner slog.Handler) slog.Handler {
	return &accessLogFilter{inner: inner}
}

func (h *accessLogFilter) Enabled(ctx context.Context, level slog.Level) bool {
	return h.inner.Enabled(ctx, level)
}

func (h *accessLogFilter) Handle(ctx context.Context, record slog.Record) error {
	access := false
	record.Attrs(func(a slog.Attr) bool {
		if a.Key == httplog.AccessLogAttr {
			access = true
			return false
		}
		return true
	})
	if access {
		return nil
	}
	return h.inner.Handle(ctx, record)
}

func (h *accessLogFilter) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &accessLogFilter{inner: h.inner.WithAttrs(attrs)}
}

func (h *accessLogFilter) WithGroup(name string) slog.Handler {
	return &accessLogFilter{inner: h.inner.WithGroup(name)}
}
