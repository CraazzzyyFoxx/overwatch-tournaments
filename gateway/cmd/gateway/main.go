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
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apiver"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/app"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/balancer"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/cachecontrol"
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
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/ratelimit"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/replay"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/respcache"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/safego"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/stream"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tracing"
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
	// Make the gateway logger the slog default so background-goroutine panic
	// recovery (safego) and any ctx-less log calls route to Loki + Sentry too.
	slog.SetDefault(logger)

	rootCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// OpenTelemetry tracing (OTLP gRPC -> otel-collector -> Tempo), joining the
	// distributed traces the Python services already emit. No-op when
	// TRACING_ENABLED is false. The deferred shutdown flushes buffered spans
	// after srv.Shutdown returns.
	traceShutdown, err := tracing.Init(rootCtx, cfg.Tracing, cfg.Sentry.Release, cfg.Environment, logger)
	if err != nil {
		return err
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = traceShutdown(ctx)
	}()

	// Postgres pool for read-only queries (event replay + ACL membership).
	pool, err := db.Connect(rootCtx, cfg.DatabaseURL, cfg.DBPgBouncer, cfg.DBMaxConns, cfg.DBStatementTimeout)
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

	// Usage metrics (Prometheus): per-route request stats + active users. The
	// recorder buffers active-user IDs and flushes them to Redis (HyperLogLog).
	// Created before the RPC client so the bulkhead can report shed requests.
	mtr := metrics.New()
	activeUsers := metrics.NewRecorder(rdb, logger)

	// RPC client for calling identity-svc (and future headless domain services)
	// over RabbitMQ request-reply. Non-blocking: reconnects in the background.
	// Per-queue in-flight cap sheds overload with an immediate 503 (see
	// GATEWAY_RPC_MAX_INFLIGHT); every publish carries a TTL + x-deadline-ms.
	rpcClient := rpc.New(cfg.RabbitMQURL, logger,
		rpc.WithMaxInFlight(cfg.RPCMaxInFlight),
		rpc.WithShedHook(mtr.RPCShed),
	)
	defer func() { _ = rpcClient.Close() }()
	identityHandler := identity.NewHandler(rpcClient, logger)
	// Tournament-service routes served via typed RPC through the shared edge
	// dispatcher. The resolver validates JWTs via identity-svc and injects the
	// RBAC identity for auth'd routes. Specific patterns win over the /api/v1 proxy.
	resolver := principal.New(rpcClient)
	tournamentEdge := edge.New(rpcClient, logger, resolver.Resolve)

	authn := auth.New(cfg.JWTSecret)
	// WebSocket authenticator: the same local JWT fast path, PLUS opaque
	// aqt_sk_ API keys resolved through identity-svc (ws.APIKeyAuth). Kept as a
	// separate value from authn because httplog and metrics call
	// UserFromRequest after the response is already written — resolving a key
	// there would put the identity backend on the access-log path.
	wsAuthn := authn.WithAPIKeys(ws.APIKeyAuth(resolver.PrincipalToken))
	// Anti-brute-force throttle for the auth endpoints (per client IP + path).
	// Disabled (pass-through) when GATEWAY_AUTH_RATE_LIMIT <= 0.
	authLimiter := ratelimit.New(cfg.AuthRateLimit, cfg.AuthRateWindow).OnReject(mtr.RateLimited)
	// Separate limiter bounding ws.Handler's pre-handshake custom-domain
	// lookup per client IP: /ws itself carries no auth and no rate limit, so
	// without this an unauthenticated flood of distinct fake Origin headers
	// could drive unbounded DB/cache-write load (see acceptOptionsFor).
	// Disabled (pass-through) when GATEWAY_WS_CUSTOM_DOMAIN_RATE_LIMIT <= 0.
	wsCustomDomainLimiter := ratelimit.New(cfg.WSCustomDomainRateLimit, cfg.WSCustomDomainRateWindow)

	// Wiring: workspace store satisfies both ACL interfaces (resolver + members)
	// plus ws.CustomDomainResolver, so verified white-label custom-domain
	// origins (Phase 2) are allowed dynamically without widening the static
	// WS origin allowlist.
	hub := ws.NewHub()
	wsStore := workspace.New(pool)
	authz := acl.New(wsStore, wsStore, wsStore)
	wsHandler := ws.NewHandler(
		hub,
		wsAuthn,
		authz,
		replay.New(pool, cfg.WSReplayLimit),
		cfg.WSIdleTimeout,
		logger,
		cfg.WSAllowedOrigins,
		wsStore,
		wsCustomDomainLimiter,
		activeUsers.Record,
		ws.Limits{
			MaxAnonConnsPerIP: cfg.WSMaxAnonConnsPerIP,
			MaxTopicsAnon:     cfg.WSMaxTopicsAnon,
			MaxTopicsAuth:     cfg.WSMaxTopicsAuth,
		},
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
	// /api/v1/auth/* paths are served here; the rest still proxy to auth-service.
	mux.HandleFunc("POST /api/v1/auth/validate", identityHandler.Validate)
	// Rate-limited (anti-brute-force): register/login/refresh + oauth callbacks.
	mux.HandleFunc("POST /api/v1/auth/register", authLimiter.Wrap(identityHandler.Register))
	mux.HandleFunc("POST /api/v1/auth/login", authLimiter.Wrap(identityHandler.Login))
	// Refresh meters only FAILED attempts (WrapFailures): legitimate rotations
	// from a shared VPN/NAT exit IP must not exhaust one flat per-IP budget and
	// 429 everyone behind it into a forced re-login.
	mux.HandleFunc("POST /api/v1/auth/refresh", authLimiter.WrapFailures(identityHandler.Refresh))
	mux.HandleFunc("POST /api/v1/auth/logout", identityHandler.Logout)
	mux.HandleFunc("POST /api/v1/auth/logout-all", identityHandler.LogoutAll)
	mux.HandleFunc("GET /api/v1/auth/sessions", identityHandler.Sessions)
	mux.HandleFunc("DELETE /api/v1/auth/sessions/{id}", identityHandler.RevokeSession)
	mux.HandleFunc("GET /api/v1/auth/me", identityHandler.Me)
	mux.HandleFunc("PATCH /api/v1/auth/me", identityHandler.UpdateMe)
	mux.HandleFunc("DELETE /api/v1/auth/me", identityHandler.DeleteMe)
	mux.HandleFunc("POST /api/v1/auth/set-password", identityHandler.SetPassword)
	mux.HandleFunc("POST /api/v1/auth/service/token", identityHandler.ServiceToken)
	mux.HandleFunc("POST /api/v1/auth/service/validate", identityHandler.ValidateService)
	mux.HandleFunc("POST /api/v1/auth/service/invalidate-session/{user_id}", identityHandler.InvalidateSession)
	// Top-level alias the frontend uses (use-oauth-providers / auth.service); the
	// original API exposed both this and the /oauth/providers path.
	mux.HandleFunc("GET /api/v1/auth/providers", identityHandler.OAuthProviders)
	mux.HandleFunc("GET /api/v1/auth/oauth/providers", identityHandler.OAuthProviders)
	mux.HandleFunc("GET /api/v1/auth/oauth/connections", identityHandler.OAuthConnections)
	mux.HandleFunc("GET /api/v1/auth/oauth/{provider}/url", identityHandler.OAuthURL)
	mux.HandleFunc("POST /api/v1/auth/oauth/{provider}/callback", authLimiter.Wrap(identityHandler.OAuthCallbackPost))
	mux.HandleFunc("POST /api/v1/auth/oauth/{provider}/link", identityHandler.OAuthLink)
	mux.HandleFunc("DELETE /api/v1/auth/oauth/{provider}/unlink", identityHandler.OAuthUnlink)
	// Custom-domain SSO ticket handoff (Task 8): redeems a one-time ticket
	// minted by the apex OAuth callback for the session tokens. Same
	// anti-brute-force posture as the other auth token-exchange endpoints.
	mux.HandleFunc("POST /api/v1/auth/sso/exchange", authLimiter.Wrap(identityHandler.SsoExchange))
	// Custom-domain account-linking end-ticket (Task 10R): redeems a
	// pending-link ticket minted by a custom-domain OAuth link callback and
	// attaches its provider identity to the bearer-authenticated caller.
	// Unlike sso/exchange above, this route IS authenticated.
	mux.HandleFunc("POST /api/v1/auth/link/complete", identityHandler.LinkComplete)
	mux.HandleFunc("GET /api/v1/auth/api-keys", identityHandler.ListApiKeys)
	// Key self-introspection: the calling key's own scopes/limits/expiry. The
	// literal "self" beats the /{id} patterns below by ServeMux specificity, and
	// none of those is a GET, so there is no ambiguity to resolve.
	mux.HandleFunc("GET /api/v1/auth/api-keys/self", identityHandler.SelfApiKey)
	mux.HandleFunc("POST /api/v1/auth/api-keys", identityHandler.CreateApiKey)
	mux.HandleFunc("PATCH /api/v1/auth/api-keys/{id}", identityHandler.UpdateApiKey)
	mux.HandleFunc("DELETE /api/v1/auth/api-keys/{id}", identityHandler.RevokeApiKey)
	// Quota: usage is a read of both applicable buckets, the PUT writes the
	// per-key override. ``self/quota`` is the keyed client's own budget, and
	// wins over /{id}/quota by the same ServeMux specificity as "self" above.
	mux.HandleFunc("GET /api/v1/auth/api-keys/self/quota", identityHandler.SelfApiKeyQuota)
	mux.HandleFunc("GET /api/v1/auth/api-keys/{id}/quota", identityHandler.ApiKeyQuota)
	mux.HandleFunc("PUT /api/v1/auth/api-keys/{id}/quota", identityHandler.SetApiKeyQuota)
	// RBAC admin (typed RPC into identity-svc; permission checks + cache
	// invalidation enforced in the worker's rbac_admin services).
	mux.HandleFunc("GET /api/v1/auth/rbac/permissions", identityHandler.RbacListPermissions)
	mux.HandleFunc("POST /api/v1/auth/rbac/permissions", identityHandler.RbacCreatePermission)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/permissions/{permission_id}", identityHandler.RbacDeletePermission)
	mux.HandleFunc("GET /api/v1/auth/rbac/roles", identityHandler.RbacListRoles)
	mux.HandleFunc("POST /api/v1/auth/rbac/roles", identityHandler.RbacCreateRole)
	mux.HandleFunc("GET /api/v1/auth/rbac/roles/{role_id}", identityHandler.RbacGetRole)
	mux.HandleFunc("PATCH /api/v1/auth/rbac/roles/{role_id}", identityHandler.RbacUpdateRole)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/roles/{role_id}", identityHandler.RbacDeleteRole)
	mux.HandleFunc("GET /api/v1/auth/rbac/users", identityHandler.RbacListAuthUsers)
	mux.HandleFunc("POST /api/v1/auth/rbac/users/assign-role", identityHandler.RbacAssignRole)
	mux.HandleFunc("POST /api/v1/auth/rbac/users/remove-role", identityHandler.RbacRemoveRole)
	mux.HandleFunc("GET /api/v1/auth/rbac/users/{user_id}", identityHandler.RbacGetAuthUser)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/users/{user_id}", identityHandler.RbacDeleteAuthUser)
	mux.HandleFunc("GET /api/v1/auth/rbac/users/{user_id}/roles", identityHandler.RbacGetUserRoles)
	mux.HandleFunc("GET /api/v1/auth/rbac/users/{user_id}/denies", identityHandler.RbacListUserDenies)
	mux.HandleFunc("POST /api/v1/auth/rbac/users/{user_id}/denies", identityHandler.RbacAddUserDeny)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/users/{user_id}/denies/{permission_id}", identityHandler.RbacRemoveUserDeny)
	mux.HandleFunc("POST /api/v1/auth/rbac/users/{user_id}/linked-players", identityHandler.RbacAssignLinkedPlayer)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/users/{user_id}/linked-players/{player_id}", identityHandler.RbacRemoveLinkedPlayer)
	mux.HandleFunc("GET /api/v1/auth/rbac/oauth-connections", identityHandler.RbacListOAuthConnections)
	mux.HandleFunc("DELETE /api/v1/auth/rbac/oauth-connections/{connection_id}", identityHandler.RbacDeleteOAuthConnection)
	mux.HandleFunc("GET /api/v1/auth/rbac/sessions", identityHandler.RbacListSessions)
	// Player linking (typed RPC; identity-svc resolves the active user from the bearer).
	mux.HandleFunc("POST /api/v1/auth/player/link", identityHandler.PlayerLink)
	mux.HandleFunc("DELETE /api/v1/auth/player/unlink/{player_id}", identityHandler.PlayerUnlink)
	mux.HandleFunc("GET /api/v1/auth/player/linked", identityHandler.PlayerLinked)
	mux.HandleFunc("PATCH /api/v1/auth/player/linked/{player_id}/primary", identityHandler.PlayerSetPrimary)
	// Current-user avatar (multipart -> base64 RPC body; the JSON path can't do it).
	// The resolver validates the bearer token before the multipart body is parsed.
	identityBinary := identity.NewBinary(identityHandler, resolver.Resolve)
	mux.HandleFunc("POST /api/v1/auth/me/avatar", identityBinary.AvatarSet)
	mux.HandleFunc("DELETE /api/v1/auth/me/avatar", identityBinary.AvatarDelete)
	// tournament-service: typed RPC reads + generic admin CRUD (the rest of
	// /api/v1 still proxies). Specific patterns win over the proxy.
	// Public reads go through the anonymous response cache (respcache): one
	// upstream RPC per unique URL per TTL/invalidation window instead of one
	// per page view. Invalidated below by the worker's realtime
	// tournament-changed signal; nil (disabled) when GATEWAY_RESPONSE_CACHE_TTL=0.
	respCache := respcache.New(cfg.ResponseCacheTTL, logger)
	respcache.RegisterCached(mux, tournamentEdge, tournament.PublicReadRoutes, tournament.PublicCacheableReads, respCache)
	tournamentEdge.Register(mux, tournament.AdminCrudRoutes)
	tournamentEdge.Register(mux, tournament.AdminMiscRoutes)
	tournamentEdge.Register(mux, tournament.RegistrationAdminRoutes)
	tournamentEdge.Register(mux, tournament.IntegrationsRoutes)
	// PublicWriteRoutes are mostly writes (never cached), but the public
	// participants list rides here too — the heaviest anonymous read of a
	// registration-phase tournament, with no backend cache at all.
	respcache.RegisterCached(mux, tournamentEdge, tournament.PublicWriteRoutes, tournament.PublicWriteCacheableReads, respCache)
	// Scrim rooms (docs/plans/2026-08-12-scrim-rooms.md): per-viewer reads
	// (viewer_side / can_claim depend on the identity), so never cached.
	tournamentEdge.Register(mux, tournament.ScrimRoutes)
	// division-grids + admin/stages: ambiguous patterns under ServeMux -> subtree matcher.
	mux.Handle("/api/v1/division-grids/", tournamentEdge.Subtree(tournament.DivisionGridRoutes))
	mux.Handle("/api/v1/admin/stages/", tournamentEdge.Subtree(tournament.StageSubtreeRoutes))
	// registration-teams: the crest DELETE is ambiguous with the invite-revoke
	// pattern under ServeMux, so it rides the subtree matcher. The prefix is less
	// specific than PublicWriteRoutes' precise patterns, which still win.
	mux.Handle("/api/v1/registration-teams/", tournamentEdge.Subtree(tournament.RegistrationTeamSubtreeRoutes))
	// Team logo, registered-team crest and tournament cover/logo uploads:
	// multipart -> base64 RPC body; the JSON dispatcher can't do it.
	tournamentBinary := tournament.NewBinary(rpcClient, resolver.Resolve, logger)
	mux.HandleFunc("POST /api/v1/admin/teams/{team_id}/image", tournamentBinary.TeamImageUpload)
	mux.HandleFunc("POST /api/v1/registration-teams/{team_id}/image", tournamentBinary.RegistrationTeamImageUpload)
	mux.HandleFunc("POST /api/v1/admin/tournaments/{tournament_id}/images/{slot}", tournamentBinary.TournamentImageUpload)
	// analytics-service: typed RPC reads + job-control (the rest of /api/v1/analytics
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
	// Achievement rule/library/override admin: ambiguous patterns under ServeMux
	// (rules/export vs rules/{rule_id}) -> ordered subtree matcher. Mounted at the
	// shared /api/v1/admin/ws/ prefix; tournament's balancer-statuses routes there
	// are more specific and win, so the two coexist.
	mux.Handle("/api/v1/admin/ws/", parserEdge.Subtree(parser.AchievementAdminRoutes))
	// app-service: typed RPC public reads (the rest of /api/v1 still proxies).
	// hero/map/gamemode/achievement get+list use the shared CRUD read engine.
	// Specific patterns win over the /api/v1 proxy below. Home-page aggregates
	// and /users/[slug] profile reads go through the same anonymous response
	// cache as the tournament page (mostly TTL-only — no per-user realtime
	// signal exists; see app.PublicCacheableReads).
	appEdge := edge.New(rpcClient, logger, resolver.Resolve)
	respcache.RegisterCached(mux, appEdge, app.ReadRoutes, app.PublicCacheableReads, respCache)
	appEdge.Register(mux, app.WorkspaceWriteRoutes)
	appEdge.Register(mux, app.MetadataAdminRoutes)
	appEdge.Register(mux, app.UsersAdminRoutes)
	appEdge.Register(mux, app.TournamentAdminRoutes)
	appEdge.Register(mux, app.QuotaAdminRoutes)
	appEdge.Register(mux, app.NotificationRoutes)
	appEdge.Register(mux, app.AnnouncementPublicRoutes)
	appEdge.Register(mux, app.AnnouncementAdminRoutes)
	appEdge.Register(mux, app.NotificationAdminRoutes)
	// achievements get surface: ambiguous (/{id}/users vs /user/{user_id}) -> subtree.
	mux.Handle("/api/v1/achievements/", appEdge.Subtree(app.AchievementsSubtreeRoutes))
	// Binary/multipart endpoints the JSON dispatcher can't handle: icon + asset
	// uploads (multipart -> base64 RPC) and the match-log download (base64 -> bytes).
	// The match-log link is browser-navigated, so its credential may arrive in the
	// session cookie instead of a header — hence the second resolver.
	appBinary := app.NewBinary(rpcClient, resolver.Resolve, resolver.ResolveWithSessionCookie, logger)
	mux.HandleFunc("POST /api/v1/workspaces/{id}/icon", appBinary.IconUpload)
	mux.HandleFunc("DELETE /api/v1/workspaces/{id}/icon", appBinary.IconDelete)
	mux.HandleFunc("POST /api/v1/assets/{asset_type}/{slug}", appBinary.AssetUpload)
	mux.HandleFunc("DELETE /api/v1/assets/{asset_type}/{slug}", appBinary.AssetDelete)
	mux.HandleFunc("GET /api/v1/matches/{match_id}/log", appBinary.MatchLog)
	// User avatar upload (relocated from parser-service).
	mux.HandleFunc("POST /api/v1/admin/users/{id}/avatar", appBinary.UserAvatarUpload)
	// balancer-service: typed RPC public config + admin balance/config + draft +
	// jobs. The HTTP balancer-service is decommissioned and no longer proxied; the
	// only un-migrated endpoint (SSE job stream) was dead code. Unmatched
	// /api/v1/balancer/* is guarded with 404 below.
	balancerEdge := edge.New(rpcClient, logger, resolver.Resolve)
	balancerEdge.Register(mux, balancer.PublicRoutes)
	balancerEdge.Register(mux, balancer.AdminRoutes)
	balancerEdge.Register(mux, balancer.RosterRoutes)

	balancerEdge.Register(mux, balancer.DraftReadRoutes)
	balancerEdge.Register(mux, balancer.DraftRoutes)
	balancerEdge.Register(mux, balancer.JobRoutes)
	// Multipart uploads (multipart -> base64 RPC): teams-import + job-create.
	balancerBinary := balancer.NewBinary(rpcClient, resolver.Resolve, logger)
	mux.HandleFunc("POST /api/v1/balancer/tournaments/{tournament_id}/teams/import", balancerBinary.TeamsImport)
	mux.HandleFunc("POST /api/v1/balancer/jobs", balancerBinary.JobCreate)
	// stream-service: the tournament live-stream surface. The spectator read is
	// public and rides the anonymous response cache (TTL-only — see
	// stream.PublicCacheableReads); the repoll trigger is an operator action
	// behind stream.update.
	streamEdge := edge.New(rpcClient, logger, resolver.Resolve)
	respcache.RegisterCached(mux, streamEdge, stream.PublicRoutes, stream.PublicCacheableReads, respCache)
	streamEdge.Register(mux, stream.AdminRoutes)
	// Guard the whole `/api/v1` namespace: anything not matched by a typed route
	// above must NOT fall through to the "/" frontend catch-all. The frontend
	// rewrites /api/v1/* back to the gateway (next.config.mjs), so proxying an
	// unmatched /api/v1 path to the frontend creates an infinite
	// gateway<->frontend proxy loop (hang + resource exhaustion that crash-loops
	// the frontend). Return 404 instead.
	//
	// This is the ONLY namespace guard, and that is the point of folding auth,
	// analytics, balancer, streams, notifications and announcements inside the
	// version: each used to need a guard of its own, and each wrote a hand-rolled
	// `{"detail":"Not Found"}` that the v2 envelope never reached. `apiver`
	// rewrites every legacy spelling onto /api/v1/... before routing, so an
	// unmatched legacy path lands here too — with the right body shape for the
	// version it asked for.
	mux.HandleFunc("/api/v1/", func(w http.ResponseWriter, _ *http.Request) {
		apierr.WriteError(w, http.StatusNotFound, "Not Found", "", nil)
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

	// Relay the realtime Redis bus to WebSocket subscribers, and tee it into
	// the response cache's invalidator: the worker's tournament_changed
	// consumer publishes realtime:tournament:{id}:bracket after every
	// committed tournament write (via the transactional outbox), so cached
	// public reads drop the moment the backend's own cache does. The third
	// leg is the chat revoker: a chat.visibility_changed frame re-runs the
	// topic ACL for that room's live subscribers, because the ACL is otherwise
	// only evaluated at subscribe time and an organizer hiding a chat must cut
	// off the spectators already in it. safego recovers a panic here
	// (unexpected Redis message format, etc.) instead of crashing the whole
	// process.
	legs := []events.Broadcaster{hub, ws.NewTopicRevoker(hub, authz, wsStore, logger)}
	if respCache != nil {
		legs = append(legs, respCache)
	}
	bus := events.Fanout(legs...)
	subscriber := events.New(rdb, bus, logger)
	safego.Go(func() {
		if err := subscriber.Run(rootCtx); err != nil && !errors.Is(err, context.Canceled) {
			logger.Error("realtime subscriber stopped", "err", err)
		}
	})

	// Usage metrics: drain active-user writes to Redis, refresh gauges from the
	// hub + HyperLogLog, and serve /metrics on a dedicated internal port. All wrapped
	// with safego so a metrics-path panic can't take the gateway down.
	safego.Go(func() { activeUsers.Run(rootCtx) })
	safego.Go(func() { mtr.Sampler(rootCtx, activeUsers, hub, time.Minute) })
	safego.Go(func() {
		if err := mtr.Serve(rootCtx, ":"+cfg.MetricsPort, logger); err != nil {
			logger.Error("metrics server stopped", "err", err)
		}
	})

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

	// REST middleware chain (outer to inner): Sentry -> tracing -> httplog ->
	// metrics -> mux. metrics shares httplog's *http.Request, so r.Pattern — set
	// by mux — is the matched route template for the access log and metrics
	// labels; httplog copies Pattern back to the tracing middleware's request so
	// the OTel span is named by route too. tracing sits outside httplog so the
	// request logger picks up the OTel trace_id and rpc.Call/proxy see the span
	// context. Sentry stays outermost for per-request hub + panic recovery
	// (Repanic lets net/http's own recovery run after capture).
	// Anonymous (no-bearer) per-IP throttle across the whole API mux, layered
	// under the coarse nginx limit_req. Innermost (wrapping mux) so a throttled
	// 429 is still metered + access-logged. Disabled (pass-through) when
	// GATEWAY_ANON_RATE_LIMIT <= 0.
	// cachecontrol sits just outside the limiter so every /api/* response —
	// including the limiter's own 429s — leaves with an explicit Cache-Control
	// when no upstream set one (an absent header invites heuristic caching of
	// viewer-dependent payloads by intermediaries).
	anonLimiter := ratelimit.New(cfg.AnonRateLimit, cfg.AnonRateWindow).OnReject(mtr.RateLimited)
	// Per-key throttle for workspace-scoped API keys, wrapping the same mux one
	// layer further in. It sits INSIDE WrapAnon because the two are mutually
	// exclusive (anonymous means no bearer at all) and both 429s must still be
	// metered, access-logged and given a Cache-Control. The window is fixed at a
	// minute: the budget it spends is the key's own requests_per_minute, and only
	// cfg.APIKeyRateLimit's default applies to a key that carries none.
	// resolver.APIKeyQuota short-circuits on the aqt_sk_ prefix, so session and
	// anonymous traffic reach the mux without any added identity lookup.
	//
	// Metered in Redis over the realtime bus's client (no second pool), on the
	// same q:key:{id}:rpm counter the Python enforcers charge: a key's published
	// requests_per_minute is a contract, so it cannot be multiplied by the
	// replica count the way the local anon/auth guardrails are. Fails open.
	apiKeyLimiter := ratelimit.New(cfg.APIKeyRateLimit, time.Minute).OnReject(mtr.RateLimited)
	apiKeyShared := ratelimit.NewRedis(rdb, apiKeyLimiter, logger, mtr.RateLimitRedisFallback)
	apiSurface := apiver.Middleware(cachecontrol.Middleware(anonLimiter.WrapAnon(apiKeyShared.WrapAPIKey(mux, resolver.APIKeyQuota))))
	instrumented := httplog.Middleware(mtr.Middleware(apiSurface, authn, activeUsers), logger, authn)
	traced := tracing.Middleware(instrumented)
	tracedMux := sentryhttp.New(sentryhttp.Options{Repanic: true}).Handle(traced)

	// Outer router: WS + health are served directly (bypassing tracing); every
	// other path falls through "/" to the traced REST surface.
	//
	// The socket is registered at all three spellings rather than rewritten,
	// because this mux sits OUTSIDE apiver — the middleware that folds legacy
	// paths onto the canonical one wraps the REST mux only, and putting a
	// long-lived hijacked connection behind it would buy nothing.
	root := http.NewServeMux()
	root.Handle("/api/v1/realtime/ws", wsWithRecover) // canonical
	root.Handle("/api/realtime/ws", wsWithRecover)    // legacy, sunset with LegacyPrefixes
	root.Handle("/ws", wsWithRecover)                 // legacy, the original spelling
	root.HandleFunc("GET /health", health)
	root.Handle("/", tracedMux)

	srv := &http.Server{
		Addr:    ":" + cfg.Port,
		Handler: root,
		// Bound header + body reads to blunt slowloris (a client dribbling the
		// request byte-by-byte). ReadTimeout only limits reading the REQUEST; it is
		// reset once a WebSocket is hijacked (the ws library manages its own
		// per-read deadlines) and does not cap long RPC processing or the response
		// write, so long-lived WS and long balancer requests are unaffected.
		// No write/idle timeout for that same reason.
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       60 * time.Second,
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
