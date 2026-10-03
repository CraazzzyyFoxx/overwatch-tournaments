package observability

import (
	"context"
	"errors"
	"log/slog"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
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

// accessLogFilter wraps the Sentry slog.Handler and drops records that are pure
// operational noise: the per-request access log, and errors whose cause is the
// client (or an in-flight request context) going away.
//
// The per-request access log is telemetry already shipped to stdout/Loki: as a
// Sentry Issue every edge 5xx — including internet vuln-scanner probes against
// the public IP — would open a noise issue grouped under "request completed",
// and as a Sentry Log it would flood ingest at edge throughput.
//
// Client-disconnect errors are the same story from the RPC side: every
// `log.Error("rpc failed", "err", ...)` site (edge/dispatch, app/balancer/
// identity/parser binary handlers, ws) reports a context.Canceled the moment a
// browser navigates away mid-request. Nothing is broken and nothing is
// actionable, but each distinct queue name opens its own Sentry group.
//
// Genuine faults are logged elsewhere (panics via sentryhttp, explicit .Error()
// calls with a real cause) and still reach Sentry. Only stdout/Loki keeps the
// full record in both cases.
type accessLogFilter struct {
	inner slog.Handler
}

// dropAccessLogs wraps inner so access-log and client-disconnect records never
// reach it.
func dropAccessLogs(inner slog.Handler) slog.Handler {
	return &accessLogFilter{inner: inner}
}

func (h *accessLogFilter) Enabled(ctx context.Context, level slog.Level) bool {
	return h.inner.Enabled(ctx, level)
}

func (h *accessLogFilter) Handle(ctx context.Context, record slog.Record) error {
	drop := false
	record.Attrs(func(a slog.Attr) bool {
		if a.Key == httplog.AccessLogAttr {
			drop = true
			return false
		}
		if a.Key == "err" && (isClientGone(a.Value) || isRPCUnavailable(a.Value)) {
			drop = true
			return false
		}
		return true
	})
	if drop {
		return nil
	}
	return h.inner.Handle(ctx, record)
}

// isClientGone reports whether an "err" log attribute carries a cancelled or
// expired request context — i.e. the caller went away rather than the gateway
// or an upstream service failing.
func isClientGone(v slog.Value) bool {
	err, ok := v.Resolve().Any().(error)
	if !ok {
		return false
	}
	return errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded)
}

// isRPCUnavailable reports whether an "err" log attribute is the broker being
// unreachable (not connected / dropped mid-call) or a request shed by the
// per-queue in-flight cap. All three fail every in-flight request at once and
// open one Sentry group per queue name (a single shed burst was 990 events), so
// they are Prometheus signals instead: RabbitMQ alerts for reachability,
// GatewayRPCShedding (gateway_rpc_shed_total) for backpressure.
func isRPCUnavailable(v slog.Value) bool {
	err, ok := v.Resolve().Any().(error)
	if !ok {
		return false
	}
	return rpc.IsUnavailable(err)
}

func (h *accessLogFilter) WithAttrs(attrs []slog.Attr) slog.Handler {
	return &accessLogFilter{inner: h.inner.WithAttrs(attrs)}
}

func (h *accessLogFilter) WithGroup(name string) slog.Handler {
	return &accessLogFilter{inner: h.inner.WithGroup(name)}
}
