// Package apidocs assembles the gateway's route tables into the public/admin
// documentation groups consumed by the openapi generator. It lives apart from
// the generic openapi package so that package stays domain-agnostic, and apart
// from main so the assembly is unit-testable against the real route tables.
package apidocs

import (
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/analytics"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/app"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/balancer"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/identity"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/openapi"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/parser"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/stream"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
)

func concat(slices ...[]edge.RouteSpec) []edge.RouteSpec {
	var out []edge.RouteSpec
	for _, s := range slices {
		out = append(out, s...)
	}
	return out
}

// splitQueue partitions routes by RPC subject: the one route serving `queue`,
// and the rest. Route tables are grouped by who registers them on the mux;
// documentation is grouped by subject area, and the two need not agree. Driving
// both groups off the one table keeps the RouteSpec written once — a second
// literal would be a mirror nobody updates.
func splitQueue(routes []edge.RouteSpec, queue string) (matched, rest []edge.RouteSpec) {
	for _, r := range routes {
		if r.Queue == queue {
			matched = append(matched, r)
		} else {
			rest = append(rest, r)
		}
	}
	return matched, rest
}

// Groups returns the documentation groups for the public and admin specs. The
// classification mirrors the route-table grouping: reads + public/captain
// writes + self-service auth go to the public spec; everything admin-gated
// (admin CRUD, RBAC, integrations, metadata, job control) goes to the admin
// spec. parser.Routes mixes public rank reads with admin endpoints, so it is
// split by auth mode.
func Groups() (public, admin []openapi.Group) {
	// The audit feed is served off the metadata-admin table (that table is
	// already registered and already carries non-metadata) but documents on its
	// own page — nobody looking for "who changed this" opens "Game Metadata".
	auditRoutes, metadataRoutes := splitQueue(app.MetadataAdminRoutes, "rpc.app.audit_list")

	public = []openapi.Group{
		{Tag: "Tournaments", Description: "Public tournament, encounter, match & team reads + captain/registration actions + scrim rooms.",
			Routes: concat(tournament.PublicReadRoutes, tournament.PublicWriteRoutes, tournament.RegistrationTeamSubtreeRoutes, tournament.ScrimRoutes)},
		{Tag: "Game Data", Description: "Heroes, maps, gamemodes, achievements & statistics (public reads).",
			Routes: concat(app.ReadRoutes, app.AchievementsSubtreeRoutes)},
		{Tag: "Analytics", Description: "Analytics reads (v1 public; v2 require analytics.read).",
			Routes: analytics.ReadRoutes},
		{Tag: "Streams", Description: "Live stream channels for a tournament (public read).",
			Routes: stream.PublicRoutes},
		{Tag: "Balancer & Draft", Description: "Balancer config, draft spectating reads, balance jobs.",
			Routes: concat(balancer.PublicRoutes, balancer.DraftReadRoutes, balancer.JobRoutes, balancer.DraftRoutes, balancer.BinaryPublicDocRoutes)},
		{Tag: "Ranks", Description: "OverFast rank history (public reads).",
			Routes: openapi.PublicOnly(parser.Routes)},
		{Tag: "Auth", Description: "Authentication, sessions, profile, OAuth, API keys, player linking.",
			Routes: identity.PublicDocRoutes},
		{Tag: "Notifications", Description: "Personal notification inbox + the site-wide announcement banner.",
			Routes: concat(app.NotificationRoutes, app.AnnouncementPublicRoutes)},
	}
	admin = []openapi.Group{
		{Tag: "Admin: Tournaments", Description: "Tournament/team/player/encounter/standing CRUD, stages & bespoke admin actions.",
			Routes: concat(tournament.AdminCrudRoutes, tournament.AdminMiscRoutes, tournament.StageSubtreeRoutes, tournament.BinaryDocRoutes, app.TournamentAdminRoutes)},
		{Tag: "Admin: Registration", Description: "Registration management & balancer statuses.",
			Routes: tournament.RegistrationAdminRoutes},
		{Tag: "Admin: Integrations", Description: "Challonge sync, Google Sheets, division grids.",
			Routes: concat(tournament.IntegrationsRoutes, tournament.DivisionGridRoutes)},
		{Tag: "Admin: Game Metadata", Description: "Hero/map/gamemode admin CRUD.",
			Routes: metadataRoutes},
		{Tag: "Admin: Users", Description: "User & identity admin CRUD + profile merge.",
			Routes: app.UsersAdminRoutes},
		{Tag: "Admin: Files & Assets", Description: "Workspace icons, assets, match-log download, user avatar & CSV import.",
			Routes: app.BinaryDocRoutes},
		{Tag: "Admin: Parser & Achievements", Description: "Match-log/rank admin, OverFast sync, settings, achievement engine + rules.",
			Routes: concat(openapi.AuthedOnly(parser.Routes), parser.AchievementAdminRoutes, parser.BinaryDocRoutes)},
		{Tag: "Admin: Balancer", Description: "Workspace/tournament balancer config + teams import.",
			Routes: concat(balancer.AdminRoutes, balancer.RosterRoutes, balancer.BinaryAdminDocRoutes)},
		{Tag: "Admin: Analytics", Description: "Analytics mutations & compute job control.",
			Routes: analytics.WriteRoutes},
		{Tag: "Admin: Streams", Description: "Force an immediate live-status re-poll.",
			Routes: stream.AdminRoutes},
		{Tag: "Admin: RBAC", Description: "Permissions, roles, user-role/player assignment, sessions & service tokens.",
			Routes: identity.AdminDocRoutes},
		{Tag: "Admin: Audit", Description: "Platform audit log: who changed what, when, workspace-scoped.",
			Routes: auditRoutes},
		{Tag: "Admin: Announcements", Description: "Workspace and platform-wide announcements: publish, edit, retire.",
			Routes: app.AnnouncementAdminRoutes},
		{Tag: "Admin: Notifications", Description: "Notifications a workspace produced: review and retire, plus one account's notification state.",
			Routes: concat(app.NotificationAdminRoutes, app.NotificationUserAdminRoutes)},
	}
	return public, admin
}
