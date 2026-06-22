// Package metrics exposes Prometheus usage metrics for the gateway: per-route
// request counts/latency (top endpoints), live WebSocket connections, and
// unique active users (DAU/WAU/MAU). It is served on a dedicated port so the
// metrics endpoint is never reachable through the public edge.
package metrics

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics owns a private registry and the gateway's metric collectors.
type Metrics struct {
	reg         *prometheus.Registry
	requests    *prometheus.CounterVec
	duration    *prometheus.HistogramVec
	activeUsers *prometheus.GaugeVec
	wsConns     *prometheus.GaugeVec
}

// New builds the collectors and registers them (plus Go/process runtime
// metrics) on a private registry.
func New() *Metrics {
	reg := prometheus.NewRegistry()
	reg.MustRegister(
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	)
	m := &Metrics{
		reg: reg,
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_http_requests_total",
			Help: "Total HTTP requests handled by the gateway, by route template, method and status code.",
		}, []string{"route", "method", "code"}),
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name: "gateway_http_request_duration_seconds",
			Help: "HTTP request latency in seconds, by route template and method.",
			// Wide buckets: some gateway requests legitimately run up to ~120s
			// (cold-cache reads, balancer jobs).
			Buckets: []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120},
		}, []string{"route", "method"}),
		activeUsers: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "gateway_active_users",
			Help: "Unique active users over a rolling window (window=1d|7d|30d).",
		}, []string{"window"}),
		wsConns: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Name: "gateway_ws_connections",
			Help: "Live WebSocket connections (state=total|authenticated).",
		}, []string{"state"}),
	}
	reg.MustRegister(m.requests, m.duration, m.activeUsers, m.wsConns)
	return m
}

// Handler returns the /metrics HTTP handler for this registry.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.reg, promhttp.HandlerOpts{})
}

// Serve runs a dedicated metrics HTTP server until ctx is cancelled. It blocks,
// so run it in a goroutine.
func (m *Metrics) Serve(ctx context.Context, addr string, logger *slog.Logger) error {
	mux := http.NewServeMux()
	mux.Handle("/metrics", m.Handler())
	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}

	go func() {
		<-ctx.Done()
		shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutCtx)
	}()

	logger.Info("metrics server listening", "addr", addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
