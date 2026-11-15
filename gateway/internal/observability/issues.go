package observability

import (
	"context"
	"log/slog"

	"github.com/getsentry/sentry-go"
	sentryslog "github.com/getsentry/sentry-go/slog"
)

// issueHandler turns Error/Fatal records into Sentry Issues. sentry-go 0.48
// removed issue creation from sentryslog (it only ships Logs now), so the
// gateway does it here.
type issueHandler struct {
	attrs  []slog.Attr
	prefix string // dotted WithGroup path for attrs added after it
}

func (h *issueHandler) Enabled(_ context.Context, level slog.Level) bool {
	return level >= slog.LevelError
}

func (h *issueHandler) Handle(ctx context.Context, record slog.Record) error {
	hub := sentry.GetHubFromContext(ctx)
	if hub == nil {
		hub = sentry.CurrentHub()
	}
	event := sentry.NewEvent()
	event.Level = sentry.LevelError
	if record.Level >= sentryslog.LevelFatal {
		event.Level = sentry.LevelFatal
	}
	event.Logger = "slog"
	event.Message = record.Message
	attrs := sentry.Context{}
	add := func(key string, value slog.Value) {
		value = value.Resolve()
		if err, ok := value.Any().(error); ok && event.Exception == nil {
			event.SetException(err, 10)
		}
		attrs[key] = value.String()
	}
	for _, a := range h.attrs {
		add(a.Key, a.Value)
	}
	record.Attrs(func(a slog.Attr) bool {
		add(h.prefix+a.Key, a.Value)
		return true
	})
	event.Contexts["slog"] = attrs
	hub.CaptureEvent(event)
	return nil
}

func (h *issueHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := &issueHandler{prefix: h.prefix, attrs: append([]slog.Attr(nil), h.attrs...)}
	for _, a := range attrs {
		next.attrs = append(next.attrs, slog.Attr{Key: h.prefix + a.Key, Value: a.Value})
	}
	return next
}

func (h *issueHandler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	return &issueHandler{attrs: h.attrs, prefix: h.prefix + name + "."}
}
