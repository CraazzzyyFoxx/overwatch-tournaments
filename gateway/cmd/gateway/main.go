// Command gateway is the thin Go edge service: REST reverse-proxy + WebSocket
// hub + local JWT validation. Phase 0 of the gateway architecture rewrite.
//
// It replaces Kong (REST routing) and realtime-service (WebSocket fan-out) with
// a single binary. Business logic stays in the existing services; the gateway
// only routes HTTP, validates JWTs locally, and relays the Redis realtime bus
// to WebSocket subscribers.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/acl"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/analytics"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/db"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/events"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/identity"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/principal"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/proxy"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/workspace"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ws"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if err := run(logger); err != nil {
		logger.Error("gateway exited with error", "err", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	rootCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Postgres pool for read-only queries (event replay + ACL membership).
	pool, err := db.Connect(rootCtx, cfg.DatabaseURL, cfg.DBPgBouncer)
	if err != nil {
		return err
	}
	defer pool.Close()

	// Redis client for the realtime fan-in bus.
	redisOpts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		return fmt.Errorf("parse redis url: %w", err)
	}
	rdb := redis.NewClient(redisOpts)
	defer func() { _ = rdb.Close() }()

	// RPC client for calling identity-svc (and future headless domain services)
	// over RabbitMQ request-reply. Non-blocking: reconnects in the background.
	rpcClient := rpc.New(cfg.RabbitMQURL, logger)
	defer func() { _ = rpcClient.Close() }()
	identityHandler := identity.NewHandler(rpcClient, logger)
	// Tournament-service routes served via typed RPC through the shared edge
	// dispatcher. The resolver validates JWTs via identity-svc and injects the
	// RBAC identity for auth'd routes. Specific patterns win over the /api/v1 proxy.
	resolver := principal.New(rpcClient)
	tournamentEdge := edge.New(rpcClient, logger, resolver.Resolve)

	// Wiring: workspace store satisfies both ACL interfaces (resolver + members).
	hub := ws.NewHub()
	wsStore := workspace.New(pool)
	authz := acl.New(wsStore, wsStore)
	wsHandler := ws.NewHandler(
		hub,
		auth.New(cfg.JWTSecret),
		authz,
		replay.New(pool, cfg.WSReplayLimit),
		cfg.WSIdleTimeout,
		logger,
	)

	rev, err := proxy.New(cfg.Upstreams)
	if err != nil {
		return err
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", health)
	// The gateway owns the WebSocket endpoint. Serve both the dev path (/ws) and
	// the Kong-style path (/api/realtime/ws) so the frontend connects unchanged.
	mux.Handle("/ws", wsHandler)
	mux.Handle("/api/realtime/ws", wsHandler)
	// Identity HTTP face (RPC into identity-svc). Additive: these specific
	// /api/auth/* paths are served here; the rest still proxy to auth-service.
	mux.HandleFunc("POST /api/auth/validate", identityHandler.Validate)
	mux.HandleFunc("POST /api/auth/register", identityHandler.Register)
	mux.HandleFunc("POST /api/auth/login", identityHandler.Login)
	mux.HandleFunc("POST /api/auth/refresh", identityHandler.Refresh)
	mux.HandleFunc("POST /api/auth/logout", identityHandler.Logout)
	mux.HandleFunc("POST /api/auth/logout-all", identityHandler.LogoutAll)
	mux.HandleFunc("GET /api/auth/sessions", identityHandler.Sessions)
	mux.HandleFunc("DELETE /api/auth/sessions/{id}", identityHandler.RevokeSession)
	mux.HandleFunc("GET /api/auth/me", identityHandler.Me)
	mux.HandleFunc("PATCH /api/auth/me", identityHandler.UpdateMe)
	mux.HandleFunc("POST /api/auth/set-password", identityHandler.SetPassword)
	mux.HandleFunc("POST /api/auth/service/token", identityHandler.ServiceToken)
	mux.HandleFunc("POST /api/auth/service/validate", identityHandler.ValidateService)
	mux.HandleFunc("POST /api/auth/service/invalidate-session/{user_id}", identityHandler.InvalidateSession)
	mux.HandleFunc("GET /api/auth/oauth/providers", identityHandler.OAuthProviders)
	mux.HandleFunc("GET /api/auth/oauth/connections", identityHandler.OAuthConnections)
	mux.HandleFunc("GET /api/auth/oauth/{provider}/url", identityHandler.OAuthURL)
	mux.HandleFunc("GET /api/auth/oauth/{provider}/callback", identityHandler.OAuthCallbackGet)
	mux.HandleFunc("POST /api/auth/oauth/{provider}/callback", identityHandler.OAuthCallbackPost)
	mux.HandleFunc("POST /api/auth/oauth/{provider}/link", identityHandler.OAuthLink)
	mux.HandleFunc("DELETE /api/auth/oauth/{provider}/unlink", identityHandler.OAuthUnlink)
	mux.HandleFunc("GET /api/auth/api-keys", identityHandler.ListApiKeys)
	mux.HandleFunc("POST /api/auth/api-keys", identityHandler.CreateApiKey)
	mux.HandleFunc("PATCH /api/auth/api-keys/{id}", identityHandler.UpdateApiKey)
	mux.HandleFunc("DELETE /api/auth/api-keys/{id}", identityHandler.RevokeApiKey)
	// Everything else under /api/auth/ (rbac, player, me/avatar, ...) is tunneled
	// to identity-svc's in-process ASGI app over RPC — no proxy to auth-service.
	// Typed routes above are more specific and win; this subtree catches the rest.
	mux.HandleFunc("/api/auth/", identityHandler.Tunnel)
	// tournament-service: typed RPC reads + generic admin CRUD (the rest of
	// /api/v1 still proxies). Specific patterns win over the proxy.
	tournamentEdge.Register(mux, tournament.PublicReadRoutes)
	tournamentEdge.Register(mux, tournament.AdminCrudRoutes)
	tournamentEdge.Register(mux, tournament.AdminMiscRoutes)
	tournamentEdge.Register(mux, tournament.RegistrationAdminRoutes)
	tournamentEdge.Register(mux, tournament.IntegrationsRoutes)
	tournamentEdge.Register(mux, tournament.PublicWriteRoutes)
	// division-grids + admin/stages: ambiguous patterns under ServeMux -> subtree matcher.
	mux.Handle("/api/v1/division-grids/", tournamentEdge.Subtree(tournament.DivisionGridRoutes))
	mux.Handle("/api/v1/admin/stages/", tournamentEdge.Subtree(tournament.StageSubtreeRoutes))
	// analytics-service: typed RPC reads + job-control (the rest of /api/analytics
	// still proxies). Specific patterns win over the proxy.
	analyticsEdge := edge.New(rpcClient, logger, resolver.Resolve)
	analyticsEdge.Register(mux, analytics.ReadRoutes)
	analyticsEdge.Register(mux, analytics.WriteRoutes)
	// Guard the /api/v1 namespace: anything not matched by a typed route above
	// must NOT fall through to the "/" frontend catch-all. The frontend rewrites
	// /api/v1/* back to the gateway (next.config.mjs), so proxying an unmatched
	// /api/v1 path to the frontend creates an infinite gateway<->frontend proxy
	// loop (hang + resource exhaustion that crash-loops the frontend). Return 404
	// instead. /api/v1/core/* is a more specific pattern and still proxies to
	// app-service.
	mux.Handle("/api/v1/core/", rev)
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
	})
	mux.Handle("/", rev)

	// Relay the realtime Redis bus to WebSocket subscribers.
	subscriber := events.New(rdb, hub, logger)
	go func() {
		if err := subscriber.Run(rootCtx); err != nil && !errors.Is(err, context.Canceled) {
			logger.Error("realtime subscriber stopped", "err", err)
		}
	}()

	srv := &http.Server{
		Addr:    ":" + cfg.Port,
		Handler: mux,
		// Bound only the header read. No write/idle timeout: long-lived
		// WebSockets and long balancer requests (Kong allowed 120s) must not be
		// cut off mid-flight.
		ReadHeaderTimeout: 10 * time.Second,
	}

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("gateway listening", "port", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serveErr <- err
		}
	}()

	select {
	case <-rootCtx.Done():
		logger.Info("shutdown signal received")
	case err := <-serveErr:
		return err
	}

	// Close WebSocket connections explicitly: Shutdown does not wait for
	// hijacked connections, so without this they would be cut at process exit.
	hub.CloseAll()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}

func health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}
