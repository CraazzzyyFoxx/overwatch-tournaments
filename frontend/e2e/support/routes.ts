// Every page route of the app, as reviewed data. A page.tsx added or removed
// without touching this list fails the coverage guard in web/pages.smoke.spec.ts.
// Pure data + types: the read-only project imports TOURNAMENT_TABS from here.

export type Ref = { id: number; slug: string };

/** One seeded tournament per lifecycle status that changes the public page, plus the hidden and non-Overwatch ones. */
export const TOURNAMENT_CASES = ["announcement", "registration", "live", "completed", "hidden", "lol", "deadlock"] as const;
export type TournamentCase = (typeof TOURNAMENT_CASES)[number];

/** Ids the smoke seed creates once per worker (see pages.smoke.spec.ts). */
export type SmokeData = {
  workspace: Ref;
  tournaments: Record<TournamentCase, Ref>;
  /** `team_formation: "draft"` tournament with a draft session. */
  draft: Ref;
  /** Team of the live tournament. */
  teamId: number;
  /** Open encounter of the live tournament's bracket. */
  encounterId: number;
  /** App-side player profile who plays in the live tournament. */
  player: Ref;
  achievementId: number;
  achievementRuleId: number;
  divisionVersionId: number;
  mixId: number;
  scrimToken: string;
};

/**
 * `public`: (site) pages and public tools — every viewer gets the page.
 * `admin`: the admin zone and the balancer tool — a plain user gets the denial screen.
 */
export type Access = "public" | "admin";

export type ViewerKind = "admin" | "user" | "anon";

export type PageRoute = {
  /** page.tsx path under frontend/src/app (route groups kept). */
  file: string;
  access: Access;
  url: (d: SmokeData) => string;
  /** Viewers who must get the not-found page (by design, or because the seed cannot create the entity). */
  notFoundFor?: ViewerKind[];
};

/** An id no table reaches (int4 max). */
export const MISSING_ID = 2_147_483_647;

/** Public tournament tabs ("" = overview). */
export const TOURNAMENT_TABS = ["", "rules", "participants", "maps", "teams", "bracket", "matches", "stats", "stream", "table", "format"] as const;

const site = (file: string, url: PageRoute["url"], extra: Partial<PageRoute> = {}): PageRoute => ({
  file: `(site)/${file}/page.tsx`,
  access: "public",
  url,
  ...extra,
});

const admin = (file: string, url: PageRoute["url"]): PageRoute => ({
  file: file ? `admin/${file}/page.tsx` : "admin/page.tsx",
  access: "admin",
  url,
});

// Admin tournament hub sub-pages, opened on the live tournament; the draft
// pages on the draft-formation one, where they have something to show.
const ADMIN_TOURNAMENT_PAGES = [
  "",
  "overview",
  "flow",
  "settings",
  "settings/general",
  "settings/registration",
  "settings/roster",
  "settings/pre-game",
  "settings/scoring",
  "settings/schedule",
  "settings/rules",
  "settings/preview",
  "settings/draft",
  "settings/challonge",
  "settings/admission",
  "settings/discord",
  "settings/report-form",
  "settings/links",
  "settings/danger",
  "registration",
  "registration/teams",
  "registration/form",
  "registration/rank-autofill",
  "registration/entries",
  "registration/feed",
  "teams",
  "teams/roster",
  "teams/draft",
  "bracket",
  "bracket/lobbies",
  "matches",
  "matches/reports",
  "matches/parsed",
  "matches/rooms",
  "matches/logs",
  "matches/encounters",
] as const;

const ADMIN_WORKSPACE_PAGES = ["", "general", "visibility", "domain", "discord", "branding"] as const;

export const ROUTES: PageRoute[] = [
  // ── (site) ────────────────────────────────────────────────────────────
  { file: "(site)/(home)/page.tsx", access: "public", url: () => "/" },
  site("achievements", () => "/achievements"),
  site("achievements/[id]", (d) => `/achievements/${d.achievementId}`),
  site("changelog", () => "/changelog"),
  site("docs", () => "/docs"),
  site("docs/[section]", () => "/docs/players"),
  site("docs/[section]/[slug]", () => "/docs/players/quickstart"),
  site("docs/dev/schema", () => "/docs/dev/schema"),
  site("encounters", () => "/encounters"),
  site("encounters/[id]", (d) => `/encounters/${d.encounterId}`),
  site("get-workspace", () => "/get-workspace"),
  site("invite", () => "/invite"),
  // A match is a parsed game log; log ingestion is out of scope for this stack.
  site("matches/[id]", () => `/matches/${MISSING_ID}`, { notFoundFor: ["admin", "user", "anon"] }),
  site("not-configured", () => "/not-configured"),
  site("privacy", () => "/privacy"),
  site("terms", () => "/terms"),
  site("scrims", () => "/scrims"),
  // A scrim room is members-only: holding the share link is not membership.
  site("scrims/[token]", (d) => `/scrims/${d.scrimToken}`, { notFoundFor: ["user", "anon"] }),
  site("statistics", () => "/statistics"),
  site("tournaments", () => "/tournaments"),
  site("tournaments/analytics", () => "/tournaments/analytics"),
  site("tournaments/[slug]", (d) => `/tournaments/${d.tournaments.live.slug}`),
  ...TOURNAMENT_TABS.filter(Boolean).map((tab) =>
    site(`tournaments/[slug]/${tab}`, (d) => `/tournaments/${d.tournaments.live.slug}/${tab}`)
  ),
  site(
    "tournaments/[slug]/pregame/[encounterId]",
    (d) => `/tournaments/${d.tournaments.live.slug}/pregame/${d.encounterId}`
  ),
  site("users", () => "/users"),
  site("users/[slug]", (d) => `/users/${d.player.slug}`),
  site("users/compare", () => "/users/compare"),
  site("users/heroes-compare", () => "/users/heroes-compare"),
  site("workspace/[slug]", (d) => `/workspace/${d.workspace.slug}`),

  // ── tools ─────────────────────────────────────────────────────────────
  { file: "balancer/page.tsx", access: "admin", url: (d) => `/balancer?tournament=${d.tournaments.live.id}` },
  { file: "balancer/mix/page.tsx", access: "public", url: () => "/balancer/mix" },
  { file: "balancer/mix/[gameId]/page.tsx", access: "public", url: (d) => `/balancer/mix/${d.mixId}` },
  { file: "balancer/mix/[gameId]/lobby/[letter]/page.tsx", access: "public", url: (d) => `/balancer/mix/${d.mixId}/lobby/a` },
  { file: "draft/[id]/page.tsx", access: "public", url: (d) => `/draft/${d.draft.id}` },

  // ── admin ─────────────────────────────────────────────────────────────
  admin("", () => "/admin"),
  admin("tournaments", () => "/admin/tournaments"),
  ...ADMIN_TOURNAMENT_PAGES.map((sub) =>
    admin(sub ? `tournaments/[id]/${sub}` : "tournaments/[id]", (d) => {
      const t = sub.endsWith("draft") ? d.draft : d.tournaments.live;
      return sub ? `/admin/tournaments/${t.id}/${sub}` : `/admin/tournaments/${t.id}`;
    })
  ),
  admin("people", () => "/admin/people"),
  admin("people/[id]", (d) => `/admin/people/${d.player.id}`),
  admin("teams", () => "/admin/teams"),
  admin("teams/[id]", (d) => `/admin/teams/${d.teamId}`),
  admin("matches", () => "/admin/matches"),
  admin("ranks", () => "/admin/ranks"),
  admin("members", () => "/admin/members"),
  admin("notifications", () => "/admin/notifications"),
  admin("announcements", () => "/admin/announcements"),
  admin("audit", () => "/admin/audit"),
  admin("achievements", () => "/admin/achievements"),
  admin("achievements/[id]", (d) => `/admin/achievements/${d.achievementRuleId}`),
  admin("access", () => "/admin/access"),
  ...["roles", "sessions", "permissions", "oauth", "accounts", "api-keys"].map((sub) =>
    admin(`access/${sub}`, () => `/admin/access/${sub}`)
  ),
  admin("collectors", () => "/admin/collectors"),
  ...["rank", "streams", "subscriptions"].map((sub) => admin(`collectors/${sub}`, () => `/admin/collectors/${sub}`)),
  admin("content", () => "/admin/content"),
  ...["maps", "heroes", "gamemodes", "unresolved"].map((sub) => admin(`content/${sub}`, () => `/admin/content/${sub}`)),
  admin("settings", () => "/admin/settings"),
  ...[
    "general",
    "branding",
    "domain",
    "discord",
    "visibility",
    "statuses",
    "quota",
    "subscriptions",
    "sub-roles",
    "registration-forms",
    "divisions",
    "divisions/import",
  ].map((sub) => admin(`settings/${sub}`, () => `/admin/settings/${sub}`)),
  admin("settings/divisions/v/[versionId]", (d) => `/admin/settings/divisions/v/${d.divisionVersionId}`),
  admin("workspaces", () => "/admin/workspaces"),
  admin("workspaces/new", () => "/admin/workspaces/new"),
  ...ADMIN_WORKSPACE_PAGES.map((sub) =>
    admin(sub ? `workspaces/[id]/${sub}` : "workspaces/[id]", (d) =>
      sub ? `/admin/workspaces/${d.workspace.id}/${sub}` : `/admin/workspaces/${d.workspace.id}`
    )
  ),
];
