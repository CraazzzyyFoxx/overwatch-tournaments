package observability

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"

	sentryslog "github.com/getsentry/sentry-go/slog"
	lumberjack "gopkg.in/natefinch/lumberjack.v2"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

// NewLogger builds the gateway logger: structured JSON tagged service=gateway,
// written to stdout and — when LOG_FILE is set and writable — a rotating file
// that Promtail tails into Loki. When Sentry is enabled records additionally fan
// out to it (Warn/Error -> Sentry Logs, Error/Fatal -> Issues), except the
// per-request access log, which is dropped before Sentry (see dropAccessLogs).
func NewLogger(cfg *config.Config) *slog.Logger {
	opts := &slog.HandlerOptions{
		Level:       parseLevel(cfg.Log.Level),
		ReplaceAttr: normalizeLevel,
	}
	var handler slog.Handler = slog.NewJSONHandler(logWriter(cfg.Log.File), opts)
	if cfg.Sentry.DSN != "" {
		handler = newFanout(handler, dropAccessLogs(newSentryHandler()))
	}
	return slog.New(handler).With(slog.String("service", "gateway"))
}

func newSentryHandler() slog.Handler {
	return sentryslog.Option{
		// EventLevel turns logged errors into Sentry Issues; deprecated in
		// sentry-go and slated for removal in 0.48.0 (see project notes).
		EventLevel: []slog.Level{slog.LevelError, sentryslog.LevelFatal},
		// LogLevel ships these to the Sentry Logs product. Info is omitted: the
		// gateway is a high-throughput edge and Info would flood Logs ingest.
		LogLevel:  []slog.Level{slog.LevelWarn, slog.LevelError},
		AddSource: true,
	}.NewSentryHandler(context.Background())
}

// logWriter returns stdout, or stdout + a rotating file when path is set and
// writable. A file-open failure degrades to stdout-only (warned to stderr) so
// the gateway never fails to start because of logging.
func logWriter(path string) io.Writer {
	if path == "" {
		return os.Stdout
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		warnLogFallback(path, err)
		return os.Stdout
	}
	// Probe writability now (lumberjack opens lazily on first write) so we can
	// fall back cleanly instead of silently dropping logs on a perms error.
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		warnLogFallback(path, err)
		return os.Stdout
	}
	_ = f.Close()
	return io.MultiWriter(os.Stdout, &lumberjack.Logger{
		Filename:   path,
		MaxSize:    100, // megabytes per file before rotation
		MaxBackups: 5,
		MaxAge:     30, // days
		Compress:   true,
	})
}

func warnLogFallback(path string, err error) {
	slog.New(slog.NewJSONHandler(os.Stderr, nil)).
		Warn("log file not writable; logging to stdout only", "path", path, "err", err)
}

// parseLevel maps a LOG_LEVEL string to a slog.Level (defaults to info).
func parseLevel(level string) slog.Level {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

// normalizeLevel renders WARN as "WARNING" so the level label matches the
// Loguru-based services and the Grafana logs dashboard filter.
func normalizeLevel(_ []string, a slog.Attr) slog.Attr {
	if a.Key == slog.LevelKey {
		if lvl, ok := a.Value.Any().(slog.Level); ok && lvl == slog.LevelWarn {
			a.Value = slog.StringValue("WARNING")
		}
	}
	return a
}
