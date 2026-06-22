package observability

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// captureHandler is a minimal slog.Handler that records the records it receives
// and is enabled only at or above minLevel.
type captureHandler struct {
	mu       sync.Mutex
	minLevel slog.Level
	records  []slog.Record
}

func (h *captureHandler) Enabled(_ context.Context, l slog.Level) bool { return l >= h.minLevel }

func (h *captureHandler) Handle(_ context.Context, r slog.Record) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.records = append(h.records, r)
	return nil
}

func (h *captureHandler) WithAttrs([]slog.Attr) slog.Handler { return h }
func (h *captureHandler) WithGroup(string) slog.Handler      { return h }

func (h *captureHandler) count() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.records)
}

func TestFanoutDeliversToAllHandlers(t *testing.T) {
	a := &captureHandler{minLevel: slog.LevelDebug}
	b := &captureHandler{minLevel: slog.LevelDebug}

	logger := slog.New(newFanout(a, b))
	logger.Info("hello", "k", "v")

	if got := a.count(); got != 1 {
		t.Fatalf("handler a got %d records, want 1", got)
	}
	if got := b.count(); got != 1 {
		t.Fatalf("handler b got %d records, want 1", got)
	}
	if a.records[0].Message != "hello" {
		t.Fatalf("handler a message = %q, want %q", a.records[0].Message, "hello")
	}
}

func TestFanoutRespectsPerHandlerEnabled(t *testing.T) {
	errOnly := &captureHandler{minLevel: slog.LevelError}
	everything := &captureHandler{minLevel: slog.LevelDebug}

	logger := slog.New(newFanout(errOnly, everything))
	logger.Info("below error threshold")

	if got := errOnly.count(); got != 0 {
		t.Fatalf("error-only handler got %d records, want 0", got)
	}
	if got := everything.count(); got != 1 {
		t.Fatalf("debug handler got %d records, want 1", got)
	}

	logger.Error("an error")
	if got := errOnly.count(); got != 1 {
		t.Fatalf("error-only handler got %d records after error, want 1", got)
	}
}

func TestFanoutPropagatesAttrsAndGroups(t *testing.T) {
	var buf bytes.Buffer
	jsonHandler := slog.NewJSONHandler(&buf, nil)
	capture := &captureHandler{minLevel: slog.LevelDebug}

	logger := slog.New(newFanout(jsonHandler, capture))
	logger.With("user", "u1").WithGroup("g").Info("hello", "k", "v")

	out := buf.String()
	if !strings.Contains(out, `"user":"u1"`) {
		t.Fatalf("WithAttrs not propagated through fanout: %s", out)
	}
	if !strings.Contains(out, `"g":{`) {
		t.Fatalf("WithGroup not propagated through fanout: %s", out)
	}
	if got := capture.count(); got != 1 {
		t.Fatalf("capture handler got %d records, want 1", got)
	}
}

func TestInitDisabledWithEmptyDSN(t *testing.T) {
	flush, err := Init(&config.Config{})
	if err != nil {
		t.Fatalf("Init with empty DSN: %v", err)
	}
	if flush == nil {
		t.Fatal("Init returned a nil flush function")
	}
	flush(time.Second) // no buffered events; must not block beyond the budget
}

func TestNewLoggerWithoutSentryReturnsPlainHandler(t *testing.T) {
	logger := NewLogger(&config.Config{})
	if logger == nil {
		t.Fatal("NewLogger returned nil")
	}
	if _, ok := logger.Handler().(*fanoutHandler); ok {
		t.Fatal("expected a plain stdout handler when DSN is empty, got fanout")
	}
}
