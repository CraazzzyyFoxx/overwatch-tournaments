"use client";

import { useMemo } from "react";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ProfileStat } from "@/components/profile/atoms";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Progress } from "@/components/ui/progress";
import { RankCrest } from "@/components/RankCrest";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useFormatter } from "@/lib/datetime/client";
import { splitHandle } from "@/lib/player";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { DraftEntry, TournamentDraft } from "@/lib/tournament/insights-query";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGrid, DivisionGridVersion } from "@/types/workspace.types";

import { useTournamentInsights } from "../../_hooks/useTournamentInsights";
import {
  baseRole,
  isTournamentRole,
  ROLE_ORDER,
  type TournamentRole
} from "../tournamentInsights.model";
import { useViewerUserId } from "../useTournamentRoster";
import { AboutTournamentCard, CardColumns, OverviewSection } from "./OverviewCards";

type Ontology = RoleOntology | null;

interface DraftState {
  /** Who is still in the pool: not a captain, not picked. */
  pool: TournamentDraft["pool"];
  byTeam: Map<number | null, DraftEntry[]>;
}

/** While the captains draft: the board's progress, the teams taking shape, what is left in the pool. */
export function OverviewDraftView({
  tournament,
  slug,
  aboutCard,
  formatCard,
  linksCard
}: Readonly<{
  tournament: Tournament;
  slug: string;
  aboutCard: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
}>) {
  const { draft } = useTournamentInsights(tournament);
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const workspaceGrid = useDivisionGrid(tournament.discipline);
  const grid = tournament.division_grid_version ?? workspaceGrid;
  const known = (id: number) =>
    Boolean(
      draft?.pool.some((player) => player.userId === id) ||
      draft?.captains.some((c) => c.userId === id)
    );
  const viewerId = useViewerUserId(known);
  const reference = (
    <AboutTournamentCard aboutCard={aboutCard} formatCard={formatCard} linksCard={linksCard} />
  );

  if (!draft) return <div className="grid min-w-0 gap-4">{reference}</div>;
  return (
    <DraftBody
      slug={slug}
      draft={draft}
      viewerId={viewerId}
      ontology={ontology}
      grid={grid}
      reference={reference}
    />
  );
}

function DraftBody({
  slug,
  draft,
  viewerId,
  ontology,
  grid,
  reference
}: Readonly<{
  slug: string;
  draft: TournamentDraft;
  viewerId: number | null;
  ontology: Ontology;
  grid: DivisionGrid | DivisionGridVersion;
  reference: React.ReactNode;
}>) {
  const t = useTranslations("tournamentDetail");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const state = useMemo<DraftState>(() => {
    const madeIds = new Set(draft.picks.map((pick) => pick.userId));
    const byTeam = new Map<number | null, DraftEntry[]>();
    for (const pick of draft.picks) {
      byTeam.set(pick.teamId, [...(byTeam.get(pick.teamId) ?? []), pick]);
    }
    return { pool: draft.pool.filter((player) => !madeIds.has(player.userId)), byTeam };
  }, [draft]);
  const captainOf = new Map(draft.captains.map((captain) => [captain.teamId, captain]));
  const made = draft.picks;
  const onClock = draft.onClock;
  const total = made.length + draft.upcoming.length;
  const onClockCaptain = onClock ? captainOf.get(onClock.teamId) : undefined;
  const autopicks = made.filter((pick) => pick.autopick).length;
  const teamLabel = (teamId: number | null) =>
    t("overview.draft.teamOf", { captain: splitHandle(captainOf.get(teamId)?.name ?? "—").name });

  return (
    <div className="grid min-w-0 gap-4">
      {viewerId ? (
        <MyDraftCard
          viewerId={viewerId}
          draft={draft}
          state={state}
          teamLabel={teamLabel}
          ontology={ontology}
        />
      ) : null}
      <CardColumns
        main={
          <OverviewSection
            title={t("overview.draft.live")}
            action={
              <Button asChild size="sm" variant="outline">
                <HoverPrefetchLink href={`/draft/${slug}`}>
                  {t("overview.draft.room")}
                </HoverPrefetchLink>
              </Button>
            }
          >
            <div className="grid gap-5">
              <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-3">
                <ProfileStat
                  label={t("overview.draft.pick")}
                  value={onClock ? onClock.overall : total}
                  sub={t("common.ofTotal", { total })}
                />
                <ProfileStat
                  label={t("overview.draft.round")}
                  value={onClock?.round ?? draft.rounds}
                  sub={t("common.ofTotal", { total: draft.rounds })}
                />
                <ProfileStat
                  label={t("overview.draft.onClock")}
                  value={onClockCaptain ? splitHandle(onClockCaptain.name).name : "—"}
                  sub={
                    onClock && isTournamentRole(baseRole(onClock.role))
                      ? t("overview.draft.needs", {
                          role: tCommon(`roles.${baseRole(onClock.role) as TournamentRole}`)
                        })
                      : undefined
                  }
                  size="md"
                  className="col-span-2 md:col-span-1"
                />
              </div>
              <Progress
                value={(made.length / Math.max(1, total)) * 100}
                size="sm"
                aria-label={t("overview.draft.progress", { made: made.length, total })}
              />
              <div>
                <Eyebrow as="h3" className="mb-1 block">
                  {t("overview.draft.latest")}
                </Eyebrow>
                <ol className="divide-y divide-[color:var(--aqt-border)]">
                  {[...made]
                    .reverse()
                    .slice(0, 8)
                    .map((pick) => (
                      <li
                        key={pick.overall}
                        className="grid grid-cols-[2.5rem_18px_minmax(0,1fr)_auto] items-center gap-x-2.5 py-2"
                      >
                        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                          #{pick.overall}
                        </span>
                        <PlayerRoleIcon
                          role={baseRole(pick.role)}
                          ontology={ontology}
                          size={16}
                          decorative
                        />
                        <span className="min-w-0">
                          <PlayerName player={{ name: pick.name }} className="text-caption" />
                          <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                            {teamLabel(pick.teamId)}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          {pick.autopick ? (
                            <Badge tone="warning" size="sm">
                              {t("overview.draft.autopick")}
                            </Badge>
                          ) : null}
                          <RankCrest rank={pick.rank} grid={grid} size={20} />
                          <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">
                            {pick.rank != null ? format.number(pick.rank) : ""}
                          </span>
                        </span>
                      </li>
                    ))}
                </ol>
              </div>
            </div>
          </OverviewSection>
        }
        side={
          <>
            <OverviewSection title={t("overview.draft.numbers")}>
              <div className="grid grid-cols-2 gap-x-6 gap-y-5">
                <ProfileStat
                  label={t("participants.results.captainsCount")}
                  value={draft.captains.length}
                  size="md"
                />
                <ProfileStat
                  label={t("overview.draft.inPool")}
                  value={state.pool.length}
                  size="md"
                />
                <ProfileStat label={t("overview.draft.picked")} value={made.length} size="md" />
                <ProfileStat
                  label={t("participants.results.autopicks")}
                  value={autopicks}
                  size="md"
                />
              </div>
            </OverviewSection>
            <PoolCard pool={state.pool} ontology={ontology} grid={grid} />
          </>
        }
      />
      {/* Full width: 26 captains read as a board in three columns, not a tail under the progress card. */}
      <TeamsForming draft={draft} state={state} ontology={ontology} />
      {reference}
    </div>
  );
}

function MyDraftCard({
  viewerId,
  draft,
  state,
  teamLabel,
  ontology
}: Readonly<{
  viewerId: number;
  draft: TournamentDraft;
  state: DraftState;
  teamLabel: (teamId: number | null) => string;
  ontology: Ontology;
}>) {
  const t = useTranslations("tournamentDetail");
  const captain = draft.captains.find((c) => c.userId === viewerId);
  const pick = draft.picks.find((p) => p.userId === viewerId);
  const teamId = captain?.teamId ?? pick?.teamId ?? null;
  const mates = teamId !== null || captain ? (state.byTeam.get(teamId) ?? []) : [];
  const nextOwnPick = captain ? draft.upcoming.find((p) => p.teamId === captain.teamId) : null;
  const picksAway =
    nextOwnPick && draft.onClock ? nextOwnPick.overall - draft.onClock.overall : null;

  return (
    <OverviewSection title={t("overview.myDraft.title")}>
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-x-10">
        <div className="grid content-start gap-2">
          <p className="font-onest text-heading font-semibold">
            {captain || pick ? teamLabel(teamId) : t("overview.myDraft.inPool")}
          </p>
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {captain
              ? picksAway === 0
                ? t("overview.myDraft.captainNow")
                : picksAway !== null
                  ? t("overview.myDraft.captainNext", { count: picksAway })
                  : t("overview.myDraft.captainDone")
              : pick
                ? t("overview.myDraft.pickedAt", { round: pick.round, overall: pick.overall })
                : t("overview.myDraft.waiting", { count: state.pool.length })}
          </p>
        </div>
        {captain || pick ? (
          <div className="md:border-l md:border-[color:var(--aqt-border)] md:pl-10">
            <Eyebrow className="mb-2 block">{t("overview.myDraft.team")}</Eyebrow>
            <ul className="flex flex-wrap gap-x-4 gap-y-2 text-caption">
              {captain ? (
                <li className="inline-flex items-center gap-1.5">
                  <PlayerRoleIcon
                    role={baseRole(captain.role)}
                    ontology={ontology}
                    size={14}
                    decorative
                  />
                  {splitHandle(captain.name).name}
                  <Crown
                    aria-label={t("participants.results.captain")}
                    className="size-3 text-[color:var(--aqt-amber)]"
                  />
                </li>
              ) : null}
              {mates.map((mate) => (
                <li key={mate.overall} className="inline-flex items-center gap-1.5">
                  <PlayerRoleIcon
                    role={baseRole(mate.role)}
                    ontology={ontology}
                    size={14}
                    decorative
                  />
                  {splitHandle(mate.name).name}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </OverviewSection>
  );
}

/** Every captain's team so far, in draft order: the board's rows, read across. */
function TeamsForming({
  draft,
  state,
  ontology
}: Readonly<{ draft: TournamentDraft; state: DraftState; ontology: Ontology }>) {
  const t = useTranslations("tournamentDetail");
  return (
    <OverviewSection title={t("overview.draft.teams")}>
      <ol className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
        {draft.captains.map((captain) => {
          const picks = state.byTeam.get(captain.teamId) ?? [];
          const onClock = draft.onClock?.teamId === captain.teamId;
          return (
            <li
              key={captain.position}
              className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2 border-b border-[color:var(--aqt-border)] py-2.5"
            >
              <span className="aqt-tnum pt-0.5 text-label text-[color:var(--aqt-fg-faint)]">
                {captain.position}
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 text-caption font-semibold">
                  {splitHandle(captain.name).name}
                  <Crown
                    aria-label={t("participants.results.captain")}
                    className="size-3 text-[color:var(--aqt-amber)]"
                  />
                  {onClock ? (
                    <Badge tone="accent" size="sm">
                      {t("overview.draft.picking")}
                    </Badge>
                  ) : null}
                </span>
                <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-label text-[color:var(--aqt-fg-muted)]">
                  {picks.length === 0 ? (
                    <span className="text-[color:var(--aqt-fg-faint)]">
                      {t("overview.draft.noPicks")}
                    </span>
                  ) : (
                    picks.map((pick) => (
                      <span key={pick.overall} className="inline-flex items-center gap-1">
                        <PlayerRoleIcon
                          role={baseRole(pick.role)}
                          ontology={ontology}
                          size={12}
                          decorative
                        />
                        {splitHandle(pick.name).name}
                      </span>
                    ))
                  )}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </OverviewSection>
  );
}

/** What is left, by role, and the highest-ranked still available in each. */
function PoolCard({
  pool,
  ontology,
  grid
}: Readonly<{
  pool: TournamentDraft["pool"];
  ontology: Ontology;
  grid: DivisionGrid | DivisionGridVersion;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  return (
    <OverviewSection title={t("overview.draft.pool")}>
      <div className="grid gap-5">
        {ROLE_ORDER.map((role) => {
          const left = pool
            .filter((player) => baseRole(player.role) === role)
            .sort((a, b) => (b.rank ?? 0) - (a.rank ?? 0));
          return (
            <div key={role}>
              <p className="mb-1.5 flex items-center gap-2 text-caption font-semibold">
                <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
                {t(`roles.${role}`)}
                <span className="font-normal text-[color:var(--aqt-fg-dim)]">{left.length}</span>
              </p>
              <ol className="grid gap-1.5">
                {left.slice(0, 3).map((player) => (
                  <li
                    key={`${player.userId}-${player.name}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <PlayerName player={{ name: player.name }} className="text-caption" />
                    <span className="flex items-center gap-2">
                      <RankCrest rank={player.rank} grid={grid} size={20} />
                      <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">
                        {player.rank != null ? format.number(player.rank) : "—"}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
    </OverviewSection>
  );
}
