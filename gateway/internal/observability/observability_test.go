package observability

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/getsentry/sentry-go"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
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

func TestDropAccessLogsFiltersAccessLogRecords(t *testing.T) {
	sink := &captureHandler{minLevel: slog.LevelDebug}
	logger := slog.New(dropAccessLogs(sink))

	// An access-log record (carries AccessLogAttr) must be dropped.
	logger.LogAttrs(context.Background(), slog.LevelError, "request completed",
		slog.Bool(httplog.AccessLogAttr, true))
	if got := sink.count(); got != 0 {
		t.Fatalf("access log reached sink: got %d records, want 0", got)
	}

	// A genuine application error (no AccessLogAttr) must pass through.
	logger.Error("boom")
	if got := sink.count(); got != 1 {
		t.Fatalf("application error dropped: got %d records, want 1", got)
	}
	if sink.records[0].Message != "boom" {
		t.Fatalf("passed message = %q, want %q", sink.records[0].Message, "boom")
	}
}

// Every `log.Error("rpc failed", "err", err)` site reports a context.Canceled
// the moment a browser navigates away mid-request. Those must not reach Sentry
// (they opened a group per RPC queue name), while an rpc failure with a real
// cause must still get through.
func TestDropAccessLogsFiltersClientDisconnects(t *testing.T) {
	sink := &captureHandler{minLevel: slog.LevelDebug}
	logger := slog.New(dropAccessLogs(sink))

	logger.Error("rpc failed", "queue", "rpc.identity.get_me", "err", context.Canceled)
	logger.Error("rpc failed", "queue", "rpc.identity.validate_token", "err", context.DeadlineExceeded)
	if got := sink.count(); got != 0 {
		t.Fatalf("client disconnect reached sink: got %d records, want 0", got)
	}

	// Wrapped causes count too: the gateway wraps with fmt.Errorf("rpc to %q: %w").
	logger.Error("rpc failed", "err", fmt.Errorf(`rpc to "rpc.identity.get_me": %w`, context.Canceled))
	if got := sink.count(); got != 0 {
		t.Fatalf("wrapped client disconnect reached sink: got %d records, want 0", got)
	}

	// A real upstream failure keeps its Sentry issue.
	logger.Error("rpc failed", "queue", "rpc.app.workspaces.get", "err", errors.New("upstream exploded"))
	if got := sink.count(); got != 1 {
		t.Fatalf("genuine rpc failure dropped: got %d records, want 1", got)
	}

	// A non-error "err" attribute must not panic or be misclassified.
	logger.Error("odd shape", "err", "just a string")
	if got := sink.count(); got != 2 {
		t.Fatalf("string err attribute dropped: got %d records, want 2", got)
	}
}

// A stack restart fails every in-flight RPC at once, and each queue name opened
// its own Sentry group — 91 events across "rpc: not connected" and "rpc:
// connection lost during call"; one shed burst of "rpc: queue overloaded" was
// 990. All three are Prometheus alerts (RabbitMQ, GatewayRPCShedding), not Issues.
func TestDropAccessLogsFiltersRPCUnavailable(t *testing.T) {
	sink := &captureHandler{minLevel: slog.LevelDebug}
	logger := slog.New(dropAccessLogs(sink))

	logger.Error("rpc failed", "queue", "rpc.identity.validate_token", "err", rpc.ErrNotConnected)
	logger.Error("rpc failed", "queue", "rpc.tournament.get_tournament", "err", rpc.ErrDisconnected)
	logger.Error("rpc failed", "queue", "rpc.stream.tournament_streams", "err", rpc.ErrOverloaded)
	if got := sink.count(); got != 0 {
		t.Fatalf("rpc unavailability reached sink: got %d records, want 0", got)
	}

	// Wrapped the way dispatch wraps it: fmt.Errorf("rpc to %q: %w").
	logger.Error("rpc failed", "err", fmt.Errorf(`rpc to "rpc.balancer.draft.tournament_board": %w`, rpc.ErrDisconnected))
	logger.Error("rpc failed", "err", fmt.Errorf(`rpc to "rpc.balancer.draft.tournament_board": %w`, rpc.ErrOverloaded))
	if got := sink.count(); got != 0 {
		t.Fatalf("wrapped rpc unavailability reached sink: got %d records, want 0", got)
	}
}

// httputil.ReverseProxy panics with http.ErrAbortHandler when the client hangs
// up mid-body; sentryhttp turns that into a fatal event. It was the single
// loudest issue in the project and never actionable.
func TestIsClientDisconnect(t *testing.T) {
	cases := []struct {
		name string
		hint *sentry.EventHint
		want bool
	}{
		{"nil hint", nil, false},
		{"empty hint", &sentry.EventHint{}, false},
		{"abort handler", &sentry.EventHint{OriginalException: http.ErrAbortHandler}, true},
		{
			"abort handler recovered from panic",
			&sentry.EventHint{RecoveredException: http.ErrAbortHandler},
			true,
		},
		{"cancelled context", &sentry.EventHint{OriginalException: context.Canceled}, true},
		{"deadline exceeded", &sentry.EventHint{OriginalException: context.DeadlineExceeded}, true},
		{
			"wrapped abort handler",
			&sentry.EventHint{OriginalException: fmt.Errorf("proxy: %w", http.ErrAbortHandler)},
			true,
		},
		{"genuine fault", &sentry.EventHint{OriginalException: errors.New("nil map write")}, false},
		{"non-error panic value", &sentry.EventHint{RecoveredException: "boom"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isClientDisconnect(tc.hint); got != tc.want {
				t.Fatalf("isClientDisconnect = %v, want %v", got, tc.want)
			}
		})
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
