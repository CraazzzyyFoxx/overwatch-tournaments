package observability

import (
	"context"
	"errors"
	"log/slog"
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
