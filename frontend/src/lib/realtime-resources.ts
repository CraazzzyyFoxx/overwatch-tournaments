import { getTournamentWorkspaceQueryKeys } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.queryKeys";
import { notificationQueryKeys } from "@/lib/notification-query-keys";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { customGameKeys } from "@/services/custom-game.service";
import { workspacePlayerKeys } from "@/services/workspace-player.service";

/**
 * The invalidation vocabulary: WHAT went stale, never WHY.
 *
 * Mirrors `backend/shared/realtime/resources.json`; `realtime-resources.test.ts`
 * asserts this union and `RESOURCE_QUERY_KEYS` are exactly the manifest, so a
 * resource cannot be published without the client knowing which queries it
 * stales, and a mapping cannot outlive its resource.
 *
 * Every key below is one an existing consumer already addressed — this table
 * collected the five per-hook reason maps that disagreed with each other, it
 * did not invent a key space.
 */
export type RealtimeResource =
  | "tournament.detail"
  | "tournament.stages"
  | "tournament.encounters"
  | "tournament.standings"
  | "tournament.teams"
  | "tournament.structure"
  | "tournament.registrations"
  | "tournament.registration_form"
  | "tournament.streams"
  | "workspace.logs"
  | "workspace.pickup_mix"
  | "workspace.subscriptions"
  | "workspace.analytics_jobs"
  | "user.notifications";

/**
 * Identity a query key needs beyond the scope id.
 *
 * `workspaceId` — most tournament keys are workspace-scoped; before the
 * workspace is known those keys cannot be built at all.
 * `detailRef` — the public overview query stays keyed by the URL ref (slug or
 * legacy id) for its whole lifecycle, see `tournamentQueryKeys.detail`.
 * `tournamentId` — for a workspace-scoped resource whose consumer ALSO holds a
 * tournament-scoped key (the log console is mounted per tournament but its
 * signal is workspace-wide).
 */
export type ResourceKeyContext = {
  workspaceId?: number | null;
  detailRef?: string | number;
  tournamentId?: number | null;
};

type KeyBuilder = (scopeId: number, ctx: ResourceKeyContext) => readonly (readonly unknown[])[];

export const RESOURCE_QUERY_KEYS: Record<RealtimeResource, KeyBuilder> = {
  "tournament.detail": (id, ctx) => [
    tournamentQueryKeys.detail(ctx.detailRef ?? id),
    // The admin metadata read is the same server read and embeds the same live
    // participants_count / registrations_count.
    getTournamentWorkspaceQueryKeys(id).tournament,
  ],
  "tournament.stages": (id) => [getTournamentWorkspaceQueryKeys(id).stages],
  "tournament.encounters": (id) => [
    tournamentQueryKeys.encounters(id),
    getTournamentWorkspaceQueryKeys(id).encounters,
  ],
  "tournament.standings": (id) => [
    tournamentQueryKeys.standings(id),
    tournamentQueryKeys.heroPlaytime(id),
    getTournamentWorkspaceQueryKeys(id).standings,
    getTournamentWorkspaceQueryKeys(id).standingsTable,
  ],
  "tournament.teams": (id) => [
    tournamentQueryKeys.teams(id),
    getTournamentWorkspaceQueryKeys(id).teams,
    // The balancer page reads the same materialized rows.
    ["balancer-public", "balance", id],
  ],
  "tournament.structure": (id, ctx) => [
    tournamentQueryKeys.detail(ctx.detailRef ?? id),
    tournamentQueryKeys.teams(id),
    tournamentQueryKeys.standings(id),
    tournamentQueryKeys.heroPlaytime(id),
    tournamentQueryKeys.encounters(id),
    getTournamentWorkspaceQueryKeys(id).tournament,
    getTournamentWorkspaceQueryKeys(id).stages,
    getTournamentWorkspaceQueryKeys(id).standings,
    getTournamentWorkspaceQueryKeys(id).standingsTable,
    getTournamentWorkspaceQueryKeys(id).encounters,
    getTournamentWorkspaceQueryKeys(id).teams,
  ],
  "tournament.registrations": (id, ctx) => [
    tournamentQueryKeys.detail(ctx.detailRef ?? id),
    getTournamentWorkspaceQueryKeys(id).tournament,
    ["balancer-admin", "registrations", id],
    ...(ctx.workspaceId == null
      ? []
      : [
          tournamentQueryKeys.registration(ctx.workspaceId, id),
          tournamentQueryKeys.registrationsList(ctx.workspaceId, id),
          tournamentQueryKeys.registrationTeams(ctx.workspaceId, id),
        ]),
  ],
  // Deliberately narrow: admin configuration a signup does not touch. It used
  // to ride along with every registration write — ~2500 reads a day on prod
  // against 9 actual edits.
  "tournament.registration_form": (id, ctx) =>
    ctx.workspaceId == null ? [] : [tournamentQueryKeys.registrationForm(ctx.workspaceId, id)],
  "tournament.streams": (id) => [tournamentQueryKeys.streams(id)],
  "workspace.logs": (id, ctx) => [
    ["admin", "workspace", id, "log-history"],
    // The console is mounted per tournament but the parser's signal is
    // workspace-wide, so the tournament-scoped variant of the same key only
    // exists when a tournament is in context (TournamentLogsTab).
    ...(ctx.tournamentId == null ? [] : [getTournamentWorkspaceQueryKeys(ctx.tournamentId).logHistory]),
  ],
  "workspace.pickup_mix": (id) => [customGameKeys.all(id), workspacePlayerKeys.all(id)],
  "workspace.subscriptions": () => [["admin", "subscriptions"]],
  "workspace.analytics_jobs": (id) => [
    ["analytics-active-job", id],
    ["analytics"],
    ["analytics-standings-distribution"],
    ["analytics-match-quality"],
  ],
  "user.notifications": () => [notificationQueryKeys.list()],
};

/**
 * Resources whose staleness a query refetch cannot fix.
 *
 * `tournament.structure` alone: which sections a tournament page has is decided
 * during server rendering, so the client has to re-run the route. Replaces the
 * former `shouldRefreshRoute` flag that hung off the `structure_changed` reason.
 */
export const ROUTE_REFRESH_RESOURCES: Record<RealtimeResource, true | undefined> = {
  "tournament.detail": undefined,
  "tournament.stages": undefined,
  "tournament.encounters": undefined,
  "tournament.standings": undefined,
  "tournament.teams": undefined,
  "tournament.structure": true,
  "tournament.registrations": undefined,
  "tournament.registration_form": undefined,
  "tournament.streams": undefined,
  "workspace.logs": undefined,
  "workspace.pickup_mix": undefined,
  "workspace.subscriptions": undefined,
  "workspace.analytics_jobs": undefined,
  "user.notifications": undefined,
};

/** Every key the named resources stale, de-duplicated by serialized key. */
export function resourceQueryKeys(
  resources: Iterable<RealtimeResource>,
  scopeId: number,
  ctx: ResourceKeyContext = {},
): readonly (readonly unknown[])[] {
  const seen = new Map<string, readonly unknown[]>();
  for (const resource of resources) {
    const build = RESOURCE_QUERY_KEYS[resource];
    if (!build) {
      continue;
    }
    for (const key of build(scopeId, ctx)) {
      seen.set(JSON.stringify(key), key);
    }
  }
  return [...seen.values()];
}
