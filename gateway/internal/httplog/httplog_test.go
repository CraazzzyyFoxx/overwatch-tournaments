package httplog

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newBuf(t *testing.T) (*slog.Logger, *bytes.Buffer) {
	t.Helper()
	var buf bytes.Buffer
	return slog.New(slog.NewJSONHandler(&buf, nil)), &buf
}

// lines parses the buffer into one decoded JSON object per log line.
func lines(t *testing.T, buf *bytes.Buffer) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, raw := range bytes.Split(bytes.TrimSpace(buf.Bytes()), []byte("\n")) {
		if len(raw) == 0 {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal(raw, &m); err != nil {
			t.Fatalf("invalid log line %q: %v", raw, err)
		}
		out = append(out, m)
	}
	return out
}

func TestMiddlewareGeneratesAndEchoesCorrelationID(t *testing.T) {
	base, buf := newBuf(t)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/x/{id}", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	h := Middleware(mux, base, nil)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/x/5", nil))

	cid := rec.Header().Get(RequestIDHeader)
	if cid == "" {
		t.Fatal("missing X-Request-ID in response")
	}
	if rec.Header().Get(CorrelationIDHeader) != cid {
		t.Fatalf("X-Correlation-ID = %q, want %q", rec.Header().Get(CorrelationIDHeader), cid)
	}

	ls := lines(t, buf)
	if len(ls) != 1 {
		t.Fatalf("got %d log lines, want 1", len(ls))
	}
	entry := ls[0]
	if entry["msg"] != "request completed" {
		t.Errorf("msg = %v", entry["msg"])
	}
	if entry["route"] != "/api/x/{id}" {
		t.Errorf("route = %v, want /api/x/{id}", entry["route"])
	}
	if entry["status"] != float64(204) {
		t.Errorf("status = %v, want 204", entry["status"])
	}
	if entry["correlation_id"] != cid {
		t.Errorf("correlation_id = %v, want %v", entry["correlation_id"], cid)
	}
}

func TestMiddlewareReusesIncomingRequestID(t *testing.T) {
	base, buf := newBuf(t)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /ping", func(http.ResponseWriter, *http.Request) {})
	h := Middleware(mux, base, nil)

	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	req.Header.Set(RequestIDHeader, "incoming-123")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := rec.Header().Get(RequestIDHeader); got != "incoming-123" {
		t.Fatalf("echoed id = %q, want incoming-123", got)
	}
	if ls := lines(t, buf); ls[0]["correlation_id"] != "incoming-123" {
		t.Fatalf("logged correlation_id = %v, want incoming-123", ls[0]["correlation_id"])
	}
}

func TestMiddlewareBindsRequestLogger(t *testing.T) {
	base, buf := newBuf(t)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /inner", func(_ http.ResponseWriter, r *http.Request) {
		From(r.Context()).Info("handler log")
	})
	h := Middleware(mux, base, nil)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/inner", nil))

	var inner map[string]any
	for _, entry := range lines(t, buf) {
		if entry["msg"] == "handler log" {
			inner = entry
		}
	}
	if inner == nil {
		t.Fatal("handler log line not found")
	}
	if inner["correlation_id"] == nil || inner["correlation_id"] == "" {
		t.Fatalf("handler log missing correlation_id: %v", inner)
	}
}

func TestFromFallsBackToDefault(t *testing.T) {
	if From(context.Background()) == nil {
		t.Fatal("From returned nil for an empty context")
	}
}

func TestLevelForStatus(t *testing.T) {
	cases := map[int]slog.Level{
		200: slog.LevelInfo,
		301: slog.LevelInfo,
		404: slog.LevelWarn,
		500: slog.LevelError,
		503: slog.LevelError,
	}
	for status, want := range cases {
		if got := levelForStatus(status); got != want {
			t.Errorf("levelForStatus(%d) = %v, want %v", status, got, want)
		}
	}
}
