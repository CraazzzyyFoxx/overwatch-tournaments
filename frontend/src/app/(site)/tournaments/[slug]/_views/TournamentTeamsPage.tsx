"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LayoutGrid, List } from "lucide-react";
import { useTranslations } from "next-intl";

import { Tournament } from "@/types/tournament.types";
import { Player, Team } from "@/types/team.types";
import type { Encounter } from "@/types/encounter.types";
import type { Hero } from "@/types/hero.types";
import type { Registration } from "@/types/registration.types";
import encounterService from "@/services/encounter.service";
import registrationService from "@/services/registration.service";
import teamService from "@/services/team.service";
import { HeroStrip } from "@/components/hero/HeroImage";
import { TournamentTeamCard } from "@/components/TournamentTeamCard";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TeamLogo } from "@/components/TeamName";
import { FilterChip } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { isEncounterCompleted } from "@/lib/encounter/status";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster/shape";
import { isTournamentStatusEnded } from "@/lib/tournament/status";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { cn } from "@/lib/utils";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useQueryParams } from "@/hooks/useQueryParams";
import { formatSubRoleLabel, getPlayerSlug, sortTeamPlayers } from "@/utils/player";

import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentTeamsSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import { ViewSegment, readViewParam } from "../_components/ViewSegment";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";
import { useHeroesMap } from "./_components/participantsColumns";

const VIEWS = ["list", "cards"] as const;
type TeamsView = (typeof VIEWS)[number];

const SORTS = ["placement", "group", "sr", "name"] as const;
type SortBy = (typeof SORTS)[number];

/** Remembers the reader's pick across tournaments; the URL still outranks it. */
const VIEW_STORAGE_KEY = "owt:teams-view";

/**
 * `<mark>` on its own is a yellow block from the user agent, unreadable on the
 * dark surface. The element stays — it is what "this is the match" means to
 * assistive tech — and only the colours come from the tokens.
 */
const MARK_CLASS =
  "rounded-[3px] bg-[color:color-mix(in_srgb,var(--aqt-teal)_22%,transparent)] px-0.5 text-[color:var(--aqt-fg)]";

/** Slot code -> the canonical role name `PlayerRoleIcon` maps to a glyph. */
const SLOT_ROLE: Record<RosterSlotCode, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex"
};

/** A team's settled series record. `null` when encounters are unavailable. */
type TeamRecord = { won: number; lost: number };

/**
 * The remembered view is an external store, not React state: it lives in
 * `localStorage`, which the server cannot read. `useSyncExternalStore` is what
 * makes that legal — the server and the hydrating client both take
 * `serverStoredView` (`null`, i.e. "no preference yet"), so the markup agrees,
 * and the real value arrives on the first post-hydration pass.
 *
 * `readStoredView` returns a string or `null`, so repeated calls compare equal
 * and React never sees a store that refuses to settle.
 */
function readStoredView(): TeamsView | null {
  try {
    const saved = window.localStorage.getItem(VIEW_STORAGE_KEY);
    return saved === "list" || saved === "cards" ? saved : null;
  } catch {
    // Private-mode Safari and a locked-down Node both throw on access; a
    // remembered view is a convenience, never a reason to fail the page.
    return null;
  }
}

const serverStoredView = () => null;

// `localStorage` does not notify anyone, so the writer announces the change.
// Module scope because `useSyncExternalStore` keys on callback identity.
const storedViewListeners = new Set<() => void>();
const subscribeStoredView = (onStoreChange: () => void) => {
  storedViewListeners.add(onStoreChange);
  return () => {
    storedViewListeners.delete(onStoreChange);
  };
};

function writeStoredView(view: TeamsView) {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // See `readStoredView`.
  }
  for (const listener of storedViewListeners) listener();
}

/**
 * `true` below the `sm` breakpoint, where `ViewSegment` hides itself. The view
 * follows: a link carrying `?view=cards` opened on a phone still gets the list,
 * because there is no control there to switch back with.
 */
function useIsNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 639px)");
    const sync = () => setNarrow(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return narrow;
}

/** Battletags and the team name, lowercased once per team for the search. */
function matchesSearch(team: Team, needle: string): boolean {
  if (needle === "") return true;
  if (team.name.toLowerCase().includes(needle)) return true;
  return team.players.some((player) => player.name.toLowerCase().includes(needle));
}

function compareTeams(a: Team, b: Team, sortBy: SortBy): number {
  switch (sortBy) {
    case "placement": {
      const ap = a.placement ?? Number.POSITIVE_INFINITY;
      const bp = b.placement ?? Number.POSITIVE_INFINITY;
      return ap - bp || a.name.localeCompare(b.name);
    }
    case "group": {
      const ag = a.group?.name ?? "";
      const bg = b.group?.name ?? "";
      // Ungrouped teams sort after every named group rather than before it.
      if (ag !== bg) return ag === "" ? 1 : bg === "" ? -1 : ag.localeCompare(bg);
      return compareTeams(a, b, "placement");
    }
    case "sr":
      return (b.avg_sr ?? 0) - (a.avg_sr ?? 0) || a.name.localeCompare(b.name);
    case "name":
      return a.name.localeCompare(b.name);
  }
}

/**
 * Settled series per team. A draw counts for neither side; unplayed and live
 * matches are not a record yet.
 */
function buildRecords(encounters: Encounter[]): Map<number, TeamRecord> {
  const records = new Map<number, TeamRecord>();
  const bump = (teamId: number | null | undefined, won: boolean) => {
    if (teamId == null) return;
    const current = records.get(teamId) ?? { won: 0, lost: 0 };
    if (won) current.won += 1;
    else current.lost += 1;
    records.set(teamId, current);
  };

  for (const encounter of encounters) {
    if (!isEncounterCompleted(encounter)) continue;
    const home = encounter.score?.home ?? 0;
    const away = encounter.score?.away ?? 0;
    if (home === away) continue;
    bump(encounter.home_team_id, home > away);
    bump(encounter.away_team_id, away > home);
  }

  return records;
}

/**
 * The roster slots of the tournament, one entry per player the shape asks for,
 * paired positionally with the team's roster. `sortTeamPlayers` orders players
 * tank -> damage -> support -> flex, the same canonical order the slot codes
 * come in, so index pairing lands each glyph on its own player.
 */
function rosterSlots(tournament: Tournament, team: Team): { role: string; player?: Player }[] {
  const players = sortTeamPlayers(team.players);
  const shape = tournament.roster_shape;

  if (!shape) {
    // No shape entity on this read: the team's own roster is the shape.
    return players.map((player) => ({ role: normalizePlayerRole(player.role), player }));
  }

  const slots: { role: string; player?: Player }[] = [];
  for (const code of ROSTER_SLOT_CODES) {
    for (let index = 0; index < (shape.slots[code] ?? 0); index += 1) {
      slots.push({ role: SLOT_ROLE[code] });
    }
  }
  return slots.map((slot, index) => {
    const player = players[index];
    // The player's own role is the truth when one fills the slot; the slot's
    // role only labels a seat nobody took.
    return player ? { role: normalizePlayerRole(player.role), player } : slot;
  });
}

/**
 * The list's column tracks: seed · logo slot · name · AVG SR · [role glyphs] ·
 * W–L · chevron. The logo track is always reserved so names align whether or
 * not a team uploaded an image (`TeamLogo` renders nothing without one). The
 * glyph track exists only for a shape with role slots — an all-flex roster
 * would show five identical glyphs, which says nothing.
 */
function listGrid(withRoles: boolean): string {
  return cn(
    "grid items-center gap-2 text-ui sm:gap-3",
    "grid-cols-[2rem_1.25rem_minmax(0,1fr)_3.5rem_2.75rem_1.25rem]",
    withRoles
      ? "sm:grid-cols-[2.5rem_1.25rem_minmax(0,1fr)_4rem_auto_3.5rem_1.25rem]"
      : "sm:grid-cols-[2.5rem_1.25rem_minmax(0,1fr)_4rem_3.5rem_1.25rem]"
  );
}

/** Role · battletag · division+SR · [heroes] · notes. The name track is capped
 *  so the division does not drift to the far edge of a wide row. */
function rosterGrid(withHeroes: boolean): string {
  return cn(
    "grid items-center gap-2",
    withHeroes
      ? "grid-cols-[3rem_minmax(0,16rem)_6rem_4.5rem_minmax(0,1fr)]"
      : "grid-cols-[3rem_minmax(0,16rem)_6rem_minmax(0,1fr)]"
  );
}

/**
 * The heroes a player declared for the role they were drafted into (§5 ③).
 * The public teams read carries no hero data, so the source is the same
 * registration list the participants pool shows — declared picks, not
 * playtime. A player without a registration (team-registration tournaments,
 * hand-added substitutes) has none.
 */
function declaredHeroes(
  player: Player,
  registration: Registration | undefined,
  heroesMap: Map<string, Hero>
): Hero[] {
  if (!registration) return [];
  const roles = registration.roles ?? [];
  const wanted = normalizePlayerRole(player.role);
  const role =
    roles.find((entry) => normalizePlayerRole(entry.role) === wanted) ??
    roles.find((entry) => entry.is_primary) ??
    roles[0];
  return (role?.top_heroes ?? [])
    .slice(0, 3)
    .map((slug) => heroesMap.get(slug) ?? ({ name: slug, slug, image_path: "", role: wanted } as Hero));
}

const TeamRosterRow = ({
  player,
  tournament,
  needle,
  heroes,
  withHeroes
}: {
  player: Player;
  tournament: Tournament;
  needle: string;
  heroes: Hero[];
  withHeroes: boolean;
}) => {
  const t = useTranslations();
  const workspaceGrid = useDivisionGrid();
  const grid = tournament.division_grid_version ?? workspaceGrid;
  const name = player.name;
  const role = normalizePlayerRole(player.role);
  const notes = [
    formatSubRoleLabel(player.sub_role),
    // "New role" is a fact about a role: a flex player has none to be new to,
    // and in a flex tournament the flag is set on everyone.
    player.is_newcomer_role && role !== "Flex" ? t("teams.roster.newcomerRole") : null,
    player.is_newcomer ? t("teams.roster.newcomer") : null
  ].filter(Boolean);

  return (
    <div className={cn(rosterGrid(withHeroes), "py-1")}>
      <span className="aqt-tnum text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
        {role}
      </span>
      <Link
        href={`/users/${getPlayerSlug(name)}`}
        className="truncate hover:text-[color:var(--aqt-teal)]"
        title={name}
      >
        {needle !== "" && name.toLowerCase().includes(needle) ? (
          <mark className={MARK_CLASS}>{name}</mark>
        ) : (
          name
        )}
      </Link>
      {/* Division as its icon (the tier name in `title`) beside the SR — one
          cell, so neither can run into the other. */}
      <span
        className="flex items-center gap-1.5"
        title={getDivisionLabel(grid, player.division) ?? undefined}
      >
        <DivisionIcon
          division={player.division}
          width={18}
          height={18}
          tournamentGrid={tournament.division_grid_version}
        />
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">{player.rank}</span>
      </span>
      {withHeroes ? (
        heroes.length > 0 ? (
          <HeroStrip
            heroes={heroes}
            size={18}
            limit={3}
            className="justify-self-start"
          />
        ) : (
          <span className="text-[color:var(--aqt-fg-dim)]">—</span>
        )
      ) : null}
      <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
        {notes.join(" · ")}
      </span>
    </div>
  );
};

/**
 * One team as a collapsed row that unfolds its roster. `<details>` and not
 * per-row state, so several teams stay open at once and the browser keeps them
 * open across a re-render.
 */
const TeamListRow = ({
  team,
  tournament,
  slug,
  record,
  needle,
  registrationsByUser,
  heroesMap
}: {
  team: Team;
  tournament: Tournament;
  slug: string;
  record: TeamRecord | null | undefined;
  needle: string;
  registrationsByUser: Map<number, Registration>;
  heroesMap: Map<string, Hero>;
}) => {
  const t = useTranslations();
  const withRoles = tournament.roster_shape?.has_role_slots ?? true;
  const slots = withRoles ? rosterSlots(tournament, team) : [];
  const subtitle = [
    team.group?.name ? t("teams.groupLabel", { name: team.group.name }) : null,
    team.placement === 1 ? t("tournamentDetail.teams.champion") : null
  ].filter(Boolean);
  const roster = sortTeamPlayers(team.players).map((player) => ({
    player,
    heroes: declaredHeroes(player, registrationsByUser.get(player.user_id), heroesMap)
  }));
  // A column of dashes says nothing: it exists only when someone declared heroes.
  const withHeroes = roster.some((entry) => entry.heroes.length > 0);

  return (
    <details className="group border-b border-[color:var(--aqt-border)]/60">
      <summary className="cursor-pointer list-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)] [&::-webkit-details-marker]:hidden">
        <div className={cn(listGrid(withRoles), "px-2 py-2.5")}>
          <span className="aqt-tnum tabular-nums text-label text-[color:var(--aqt-fg-faint)]">
            {team.placement != null ? `#${team.placement}` : ""}
          </span>
          <span className="inline-flex size-5 items-center justify-center">
            <TeamLogo team={team} size="sm" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium" title={team.name}>
              {team.name}
            </span>
            {subtitle.length > 0 ? (
              <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                {subtitle.join(" · ")}
              </span>
            ) : null}
          </span>
          <span className="aqt-tnum text-[color:var(--aqt-fg-muted)]">{team.avg_sr.toFixed(0)}</span>
          {withRoles ? (
            <span className="hidden items-center gap-0.5 sm:flex">
              {slots.map((slot, index) => (
                <span
                  key={index}
                  title={slot.player?.name ?? undefined}
                  className={cn("inline-flex", slot.player == null && "opacity-40")}
                >
                  <PlayerRoleIcon role={slot.role} size={16} label={slot.player?.name ?? undefined} />
                </span>
              ))}
            </span>
          ) : null}
          <span className="aqt-tnum text-right text-[color:var(--aqt-fg-muted)]">
            {record ? `${record.won}–${record.lost}` : "—"}
          </span>
          <span className="flex justify-end">
            <ChevronDown
              className="size-3.5 text-[color:var(--aqt-fg-faint)] transition-transform group-open:rotate-180"
              aria-hidden
            />
          </span>
        </div>
      </summary>
      <div className="mb-2 ml-2 mr-2 border-l-2 border-[color:var(--aqt-border)] py-1 pl-3 text-caption sm:ml-[4.75rem]">
        <div className={cn(rosterGrid(withHeroes), "py-0.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]")}>
          <span>{t("teams.roster.role")}</span>
          <span>{t("teams.roster.battleTag")}</span>
          <span>
            {t("teams.roster.division")} · {t("tournamentDetail.teams.sr")}
          </span>
          {withHeroes ? <span>{t("common.heroes")}</span> : null}
          <span />
        </div>
        {roster.map(({ player, heroes }) => (
          <TeamRosterRow
            key={player.id}
            player={player}
            tournament={tournament}
            needle={needle}
            heroes={heroes}
            withHeroes={withHeroes}
          />
        ))}
        <div className="mt-1.5 flex flex-wrap gap-3 border-t border-[color:var(--aqt-border)]/60 pt-1.5 text-label">
          <Link
            href={`/tournaments/${slug}/matches?team=${team.id}`}
            className="text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
          >
            {t("tournamentDetail.teams.teamMatches")}
          </Link>
          {/* Wireframe §5 ④ offers "Team profile" only when a team route exists.
              The public site has no team page, so the button is absent rather
              than dead. */}
        </div>
      </div>
    </details>
  );
};

const TournamentTeamsView = ({ tournament, slug }: { tournament: Tournament; slug: string }) => {
  const t = useTranslations();
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(tournament.id, tournament.workspace_id),
    queryFn: () =>
      teamService.getAll({
        tournamentId: tournament.id,
        workspaceId: tournament.workspace_id
      })
  });

  // Same key and same call the bracket and the matches section use, so the
  // W-L column is a cache read wherever the reader has already been.
  const encountersQuery = useQuery({
    queryKey: tournamentQueryKeys.encounters(tournament.id, tournament.workspace_id),
    queryFn: () =>
      encounterService.getAll(
        1,
        "",
        tournament.id,
        -1,
        undefined,
        undefined,
        tournament.workspace_id
      )
  });

  // Declared top heroes for the roster expansion (§5 ③) — the participants
  // section's own list and hero catalogue, so both are cache reads after one
  // visit there. Only draft/balancer tournaments register players one by one;
  // a team-registration read would come back without per-player picks.
  const hasPlayerRegistrations = tournament.team_formation !== "registration";
  const registrationsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.listRegistrations(tournament.id),
    enabled: hasPlayerRegistrations
  });
  const heroesMap = useHeroesMap({ enabled: hasPlayerRegistrations });
  const registrationsByUser = useMemo(() => {
    const byUser = new Map<number, Registration>();
    // Empty when the organizer hid the participants list; the roster expansion
    // then simply renders without declared heroes.
    for (const registration of registrationsQuery.data?.registrations ?? []) {
      if (registration.user_id !== null) byUser.set(registration.user_id, registration);
    }
    return byUser;
  }, [registrationsQuery.data]);

  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const storedView = useSyncExternalStore(subscribeStoredView, readStoredView, serverStoredView);
  const narrow = useIsNarrowViewport();
  const withRoles = tournament.roster_shape?.has_role_slots ?? true;

  const teams = useMemo(() => teamsQuery.data?.results ?? [], [teamsQuery.data]);

  const defaultSort: SortBy = isTournamentStatusEnded(tournament.status) ? "placement" : "group";
  const sortBy = readViewParam(searchParams, "sort", SORTS, defaultSort);
  const groupFilter = searchParams?.get("group") ?? null;
  const search = searchParams?.get("q") ?? "";
  const needle = search.trim().toLowerCase();
  const view = narrow ? "list" : readViewParam(searchParams, "view", VIEWS, storedView ?? "list");

  const groups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const team of teams) {
      const name = team.group?.name;
      if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [teams]);

  const visibleTeams = useMemo(
    () =>
      teams
        .filter((team) => groupFilter == null || team.group?.name === groupFilter)
        .filter((team) => matchesSearch(team, needle))
        .sort((a, b) => compareTeams(a, b, sortBy)),
    [teams, groupFilter, needle, sortBy]
  );

  const records = useMemo(() => {
    const encounters = encountersQuery.data?.results;
    return encounters ? buildRecords(encounters) : null;
  }, [encountersQuery.data]);

  const presentation = getPublicPageQueryPresentation({
    data: teamsQuery.data,
    itemCount: teams.length,
    isPending: teamsQuery.isPending,
    isError: teamsQuery.isError,
    isFetching: teamsQuery.isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void teamsQuery.refetch()} />;
  }

  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentTeamsSkeleton />;
  }

  const content = (
    <div className="space-y-4">
      {presentation.showUpdating ? <UpdatingBadge /> : null}
      {presentation.contentState === "empty" ? (
        <TournamentPageState state="empty" />
      ) : (
        <>
          <SectionToolbar
            label={t("common.filters")}
            end={
              <>
                <SearchField
                  value={search}
                  onValueChange={(value) => setParams({ q: value || null })}
                  label={t("tournamentDetail.teams.searchLabel")}
                  placeholder={t("tournamentDetail.teams.searchPlaceholder")}
                  containerClassName="w-[11rem]"
                  className="h-8 py-1"
                />
                <Select
                  value={sortBy}
                  onValueChange={(value) => {
                    const next = value as SortBy;
                    setParams({ sort: next === defaultSort ? null : next });
                  }}
                >
                  <SelectTrigger
                    aria-label={t("tournamentDetail.sortTeams")}
                    className="filter-sort h-8 w-[10.5rem] shadow-none focus:ring-0 focus:ring-offset-0"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="placement">{t("common.byPlacement")}</SelectItem>
                    <SelectItem value="group">{t("tournamentDetail.teams.byGroup")}</SelectItem>
                    <SelectItem value="sr">{t("common.byAvgSr")}</SelectItem>
                    <SelectItem value="name">{t("common.byName")}</SelectItem>
                  </SelectContent>
                </Select>
                <ViewSegment
                  param="view"
                  defaultValue={storedView ?? "list"}
                  options={[
                    {
                      value: "list",
                      label: <List aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.teams.viewList")
                    },
                    {
                      value: "cards",
                      label: <LayoutGrid aria-hidden width={14} height={14} />,
                      ariaLabel: t("tournamentDetail.teams.viewCards")
                    }
                  ]}
                  onChange={(next) => writeStoredView(next)}
                  label={t("tournamentDetail.teams.viewLabel")}
                />
              </>
            }
          >
            <FilterChip
              active={groupFilter == null}
              count={teams.length}
              onClick={() => setParams({ group: null })}
            >
              {t("common.all")}
            </FilterChip>
            {groups.map(([name, count]) => (
              <FilterChip
                key={name}
                active={groupFilter === name}
                count={count}
                onClick={() => setParams({ group: name })}
              >
                {t("common.group")} {name}
              </FilterChip>
            ))}
          </SectionToolbar>

          {visibleTeams.length === 0 ? (
            <TournamentPageState
              state="filtered-empty"
              onReset={() => setParams({ group: null, q: null })}
            />
          ) : view === "cards" ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visibleTeams.map((team) => {
                const matched =
                  needle === ""
                    ? []
                    : team.players.filter((player) => player.name.toLowerCase().includes(needle));
                return (
                  <div key={team.id} className="space-y-1">
                    {/* Wireframe §5 ⑤ keeps this card byte-for-byte; the matched
                        battletag is therefore marked above it rather than
                        inside `TournamentTeamCard`, which this screen does not
                        own. Nothing renders when nothing was searched, so the
                        card's surroundings are unchanged by default. */}
                    {matched.length > 0 ? (
                      <p className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                        {t("tournamentDetail.teams.matchedPlayers")}{" "}
                        {matched.map((player, index) => (
                          <span key={player.id}>
                            {index > 0 ? ", " : null}
                            <mark className={MARK_CLASS}>{player.name}</mark>
                          </span>
                        ))}
                      </p>
                    ) : null}
                    <TournamentTeamCard team={team} />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="border-t border-[color:var(--aqt-border)]">
              <div
                className={cn(
                  listGrid(withRoles),
                  "border-b border-[color:var(--aqt-border)] px-2 py-1.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                )}
              >
                <span>#</span>
                <span />
                <span>{t("tournamentDetail.teams.team")}</span>
                <span>{t("teams.roster.avgSr")}</span>
                {withRoles ? (
                  <span className="hidden sm:block">{t("tournamentDetail.teams.rosterColumn")}</span>
                ) : null}
                <span className="text-right">{t("tournamentDetail.teams.record")}</span>
                <span />
              </div>
              {visibleTeams.map((team) => (
                <TeamListRow
                  key={team.id}
                  team={team}
                  tournament={tournament}
                  slug={slug}
                  record={records?.get(team.id) ?? null}
                  needle={needle}
                  registrationsByUser={registrationsByUser}
                  heroesMap={heroesMap}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void teamsQuery.refetch()}
        isUpdating={teamsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

/**
 * Resolves the shared tournament overview so the route file stays a one-line
 * delegation, matching every other tournament sub-route. The overview is
 * already primed by the layout, so this is a cache read in practice — the
 * guards below only fire if that layout contract ever changes.
 */
const TournamentTeamsPage = ({ slug }: { slug: string }) => {
  // Keyed by `slug`: shares TournamentClientLayout's overview cache entry.
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentTeamsSkeleton />;
  }

  return <TournamentTeamsView tournament={tournamentQuery.data} slug={slug} />;
};

export default TournamentTeamsPage;
