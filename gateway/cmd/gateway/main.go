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

	"github.com/getsentry/sentry-go"
	sentryhttp "github.com/getsentry/sentry-go/http"
	"github.com/redis/go-redis/v9"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/acl"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/analytics"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apidocs"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/app"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/balancer"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/db"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/events"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/identity"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/metrics"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/observability"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/openapi"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/parser"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/principal"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/proxy"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/workspace"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ws"
)

func main() {
	if err := run(); err != nil {
		slog.New(slog.NewJSONHandler(os.Stderr, nil)).Error("gateway exited with error", "err", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	// Sentry: error monitoring + tracing + logs. No-op when SENTRY_DSN is empty.
	flush, err := observability.Init(cfg)
	if err != nil {
		return err
	}
	defer flush(2 * time.Second)
	logger := observability.NewLogger(cfg)

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

	// Usage metrics (Prometheus): per-route request stats + active users. The
	// recorder buffers active-user IDs and flushes them to Redis (HyperLogLog).
	mtr := metrics.New()
	activeUsers := metrics.NewRecorder(rdb, logger)
	authn := auth.New(cfg.JWTSecret)

	// Wiring: workspace store satisfies both ACL interfaces (resolver + members).
	hub := ws.NewHub()
	wsStore := workspace.New(pool)
	authz := acl.New(wsStore, wsStore)
	wsHandler := ws.NewHandler(
		hub,
		authn,
		authz,
		replay.New(pool, cfg.WSReplayLimit),
		cfg.WSIdleTimeout,
		logger,
		activeUsers.Record,
	)

	rev, err := proxy.New(cfg.Upstreams)
	if err != nil {
		return err
	}

	// mux holds the REST surface only. The WebSocket endpoints and /health are
	// registered on the outer router below so they bypass the sentryhttp
	// middleware (which would otherwise open a transaction spanning the whole
	// long-lived WS connection, and trace every health probe).
	mux := http.NewServeMux()
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
	// Top-level alias the frontend uses (use-oauth-providers / auth.service); the
	// original API exposed both this and the /oauth/providers path.
	mux.HandleFunc("GET /api/auth/providers", identityHandler.OAuthProviders)
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
	// RBAC admin (typed RPC into identity-svc; permission checks + cache
	// invalidation enforced in the worker's rbac_flows).
	mux.HandleFunc("GET /api/auth/rbac/permissions", identityHandler.RbacListPermissions)
	mux.HandleFunc("POST /api/auth/rbac/permissions", identityHandler.RbacCreatePermission)
	mux.HandleFunc("DELETE /api/auth/rbac/permissions/{permission_id}", identityHandler.RbacDeletePermission)
	mux.HandleFunc("GET /api/auth/rbac/roles", identityHandler.RbacListRoles)
	mux.HandleFunc("POST /api/auth/rbac/roles", identityHandler.RbacCreateRole)
	mux.HandleFunc("GET /api/auth/rbac/roles/{role_id}", identityHandler.RbacGetRole)
	mux.HandleFunc("PATCH /api/auth/rbac/roles/{role_id}", identityHandler.RbacUpdateRole)
	mux.HandleFunc("DELETE /api/auth/rbac/roles/{role_id}", identityHandler.RbacDeleteRole)
	mux.HandleFunc("GET /api/auth/rbac/users", identityHandler.RbacListAuthUsers)
	mux.HandleFunc("POST /api/auth/rbac/users/assign-role", identityHandler.RbacAssignRole)
	mux.HandleFunc("POST /api/auth/rbac/users/remove-role", identityHandler.RbacRemoveRole)
	mux.HandleFunc("GET /api/auth/rbac/users/{user_id}", identityHandler.RbacGetAuthUser)
	mux.HandleFunc("GET /api/auth/rbac/users/{user_id}/roles", identityHandler.RbacGetUserRoles)
	mux.HandleFunc("GET /api/auth/rbac/users/{user_id}/denies", identityHandler.RbacListUserDenies)
	mux.HandleFunc("POST /api/auth/rbac/users/{user_id}/denies", identityHandler.RbacAddUserDeny)
	mux.HandleFunc("DELETE /api/auth/rbac/users/{user_id}/denies/{permission_id}", identityHandler.RbacRemoveUserDeny)
	mux.HandleFunc("POST /api/auth/rbac/users/{user_id}/linked-players", identityHandler.RbacAssignLinkedPlayer)
	mux.HandleFunc("DELETE /api/auth/rbac/users/{user_id}/linked-players/{player_id}", identityHandler.RbacRemoveLinkedPlayer)
	mux.HandleFunc("GET /api/auth/rbac/oauth-connections", identityHandler.RbacListOAuthConnections)
	mux.HandleFunc("DELETE /api/auth/rbac/oauth-connections/{connection_id}", identityHandler.RbacDeleteOAuthConnection)
	mux.HandleFunc("GET /api/auth/rbac/sessions", identityHandler.RbacListSessions)
	// Player linking (typed RPC; identity-svc resolves the active user from the bearer).
	mux.HandleFunc("POST /api/auth/player/link", identityHandler.PlayerLink)
	mux.HandleFunc("DELETE /api/auth/player/unlink/{player_id}", identityHandler.PlayerUnlink)
	mux.HandleFunc("GET /api/auth/player/linked", identityHandler.PlayerLinked)
	mux.HandleFunc("PATCH /api/auth/player/linked/{player_id}/primary", identityHandler.PlayerSetPrimary)
	// Current-user avatar (multipart -> base64 RPC body; the JSON path can't do it).
	identityBinary := identity.NewBinary(identityHandler)
	mux.HandleFunc("POST /api/auth/me/avatar", identityBinary.AvatarSet)
	mux.HandleFunc("DELETE /api/auth/me/avatar", identityBinary.AvatarDelete)
	// Guard the /api/auth namespace: the HTTP-over-RPC tunnel + auth-service proxy
	// are gone — every /api/auth/* path is a typed RPC route above. Anything
	// unmatched must NOT fall through to the "/" frontend catch-all (next.config
	// rewrites /api/auth/* back to the gateway -> infinite gateway<->frontend proxy
	// loop). Return 404 instead, mirroring the /api/v1 + /api/analytics guards.
	mux.HandleFunc("/api/auth/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
	})
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
	// parser-service domains folded into /api/v1 (match-log, OverFast rank,
	// achievement engine + rules admin, metadata sync, settings, discord-channel,
	// bootstrap importers), served as typed RPC. Un-migrated parser paths still
	// proxy to parser-service on their original /api/parser/* addresses.
	parserEdge := edge.New(rpcClient, logger, resolver.Resolve)
	parserEdge.Register(mux, parser.Routes)
	// Multipart match-log upload (files[] -> base64 RPC body) the JSON dispatcher
	// can't handle.
	parserBinary := parser.NewBinary(rpcClient, resolver.Resolve, logger)
	mux.HandleFunc("POST /api/v1/admin/logs/upload", parserBinary.AdminLogsUpload)
	mux.HandleFunc("POST /api/v1/teams/create/balancer", parserBinary.TeamsBalancerUpload)
	// Achievement rule/library/override admin: ambiguous patterns under ServeMux
	// (rules/export vs rules/{rule_id}) -> ordered subtree matcher. Mounted at the
	// shared /api/v1/admin/ws/ prefix; tournament's balancer-statuses routes there
	// are more specific and win, so the two coexist.
	mux.Handle("/api/v1/admin/ws/", parserEdge.Subtree(parser.AchievementAdminRoutes))
	// app-service: typed RPC public reads (the rest of /api/v1 still proxies).
	// hero/map/gamemode/achievement get+list use the shared CRUD read engine.
	// Specific patterns win over the /api/v1 proxy below.
	appEdge := edge.New(rpcClient, logger, resolver.Resolve)
	appEdge.Register(mux, app.ReadRoutes)
	appEdge.Register(mux, app.WorkspaceWriteRoutes)
	appEdge.Register(mux, app.MetadataAdminRoutes)
	appEdge.Register(mux, app.UsersAdminRoutes)
	// achievements get surface: ambiguous (/{id}/users vs /user/{user_id}) -> subtree.
	mux.Handle("/api/v1/achievements/", appEdge.Subtree(app.AchievementsSubtreeRoutes))
	// Binary/multipart endpoints the JSON dispatcher can't handle: icon + asset
	// uploads (multipart -> base64 RPC) and the match-log download (base64 -> bytes).
	appBinary := app.NewBinary(rpcClient, resolver.Resolve, logger)
	mux.HandleFunc("POST /api/v1/workspaces/{id}/icon", appBinary.IconUpload)
	mux.HandleFunc("DELETE /api/v1/workspaces/{id}/icon", appBinary.IconDelete)
	mux.HandleFunc("POST /api/v1/assets/{asset_type}/{slug}", appBinary.AssetUpload)
	mux.HandleFunc("DELETE /api/v1/assets/{asset_type}/{slug}", appBinary.AssetDelete)
	mux.HandleFunc("GET /api/v1/matches/{match_id}/log", appBinary.MatchLog)
	// User avatar upload + CSV/Sheets user import (relocated from parser-service).
	mux.HandleFunc("POST /api/v1/admin/users/{id}/avatar", appBinary.UserAvatarUpload)
	mux.HandleFunc("POST /api/v1/user/create/csv", appBinary.UsersCsvImport)
	// balancer-service: typed RPC public config + admin balance/config + draft +
	// jobs. The HTTP balancer-service is decommissioned and no longer proxied; the
	// only un-migrated endpoint (SSE job stream) was dead code. Unmatched
	// /api/balancer/* is guarded with 404 below.
	balancerEdge := edge.New(rpcClient, logger, resolver.Resolve)
	balancerEdge.Register(mux, balancer.PublicRoutes)
	balancerEdge.Register(mux, balancer.AdminRoutes)
	balancerEdge.Register(mux, balancer.DraftReadRoutes)
	balancerEdge.Register(mux, balancer.DraftRoutes)
	balancerEdge.Register(mux, balancer.JobRoutes)
	// Multipart uploads (multipart -> base64 RPC): teams-import + job-create.
	balancerBinary := balancer.NewBinary(rpcClient, resolver.Resolve, logger)
	mux.HandleFunc("POST /api/balancer/tournaments/{tournament_id}/teams/import", balancerBinary.TeamsImport)
	mux.HandleFunc("POST /api/balancer/jobs", balancerBinary.JobCreate)
	// Guard the /api/v1 namespace: anything not matched by a typed route above
	// must NOT fall through to the "/" frontend catch-all. The frontend rewrites
	// /api/v1/* back to the gateway (next.config.mjs), so proxying an unmatched
	// /api/v1 path to the frontend creates an infinite gateway<->frontend proxy
	// loop (hang + resource exhaustion that crash-loops the frontend). Return 404
	// instead. app-service (/api/v1/*) is now fully served by the typed app
	// routes above; unmatched /api/v1/* falls here too (404, no proxy).
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
	})
	// /api/analytics is fully served by the typed analytics routes above (RPC into
	// analytics-svc); the HTTP analytics-service is decommissioned and no longer
	// proxied. Guard unmatched /api/analytics/* with 404 (same gateway<->frontend
	// loop hazard as /api/v1, since next.config rewrites /api/analytics -> gateway).
	mux.HandleFunc("/api/analytics/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
	})
	// /api/balancer is fully served by the typed balancer routes above (RPC into
	// balancer-worker); the HTTP balancer-service is decommissioned and no longer
	// proxied. Guard unmatched /api/balancer/* with 404 (same gateway<->frontend
	// loop hazard as /api/v1, since next.config rewrites /api/balancer -> gateway).
	mux.HandleFunc("/api/balancer/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"Not Found"}`))
	})

	// Scalar API docs: two pages generated from the route tables above. The
	// public page (/api/docs) is always served; the admin page (/api/docs/admin)
	// is gated to non-production environments (config.Docs.AdminEnabled). The spec
	// + UI paths sit outside the guarded namespaces, so they win over the "/"
	// proxy by ServeMux specificity.
	publicGroups, adminGroups := apidocs.Groups()
	docs := openapi.New(cfg.Docs, openapi.Info{
		Title:       "anak-tournaments gateway API",
		Version:     cfg.Sentry.Release,
		Description: "Auto-generated from the gateway route tables. Request/response bodies are generic objects — the concrete schemas live in the domain services.",
	}, publicGroups, adminGroups)
	docs.Register(mux)

	mux.Handle("/", rev)

	// Relay the realtime Redis bus to WebSocket subscribers.
	subscriber := events.New(rdb, hub, logger)
	go func() {
		if err := subscriber.Run(rootCtx); err != nil && !errors.Is(err, context.Canceled) {
			logger.Error("realtime subscriber stopped", "err", err)
		}
	}()

	// Usage metrics: drain active-user writes to Redis, refresh gauges from the
	// hub + HyperLogLog, and serve /metrics on a dedicated internal port.
	go activeUsers.Run(rootCtx)
	go mtr.Sampler(rootCtx, activeUsers, hub, time.Minute)
	go func() {
		if err := mtr.Serve(rootCtx, ":"+cfg.MetricsPort, logger); err != nil {
			logger.Error("metrics server stopped", "err", err)
		}
	}()

	// WebSocket handler with Sentry panic recovery. The read loop runs
	// synchronously in ServeHTTP, so a panic unwinds through this deferred
	// recover. Each connection gets its own cloned hub (the global hub's scope is
	// not safe for concurrent capture), carrying the request for context. The
	// query string (which may hold ?token=) is scrubbed by the BeforeSend hook.
	wsWithRecover := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hub := sentry.CurrentHub().Clone()
		hub.Scope().SetRequest(r)
		ctx := sentry.SetHubOnContext(r.Context(), hub)
		defer sentry.RecoverWithContext(ctx)
		wsHandler.ServeHTTP(w, r)
	})

	// REST middleware chain (outer to inner): Sentry -> httplog -> metrics -> mux.
	// httplog wraps the metrics handler (which wraps mux); all share the same
	// *http.Request, so r.Pattern — set by mux — is the matched route template for
	// both the access log and the metrics labels. httplog also binds a
	// request-scoped logger (correlation_id) used by the handlers' error logs.
	// Sentry stays outermost for per-request hub + tracing + panic recovery
	// (Repanic lets net/http's own recovery run after capture).
	instrumented := httplog.Middleware(mtr.Middleware(mux, authn, activeUsers), logger, authn)
	tracedMux := sentryhttp.New(sentryhttp.Options{Repanic: true}).Handle(instrumented)

	// Outer router: WS + health are served directly (bypassing tracing); every
	// other path falls through "/" to the traced REST surface.
	root := http.NewServeMux()
	root.Handle("/ws", wsWithRecover)
	root.Handle("/api/realtime/ws", wsWithRecover)
	root.HandleFunc("GET /health", health)
	root.Handle("/", tracedMux)

	srv := &http.Server{
		Addr:    ":" + cfg.Port,
		Handler: root,
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
