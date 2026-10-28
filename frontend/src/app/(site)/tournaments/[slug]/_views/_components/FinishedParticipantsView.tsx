"use client";

import { useMemo, useState } from "react";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import TeamName from "@/components/TeamName";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { PlaceBadge } from "@/components/ui/place-badge";
import { SearchField } from "@/components/ui/search-field";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useFormatter } from "@/lib/datetime/client";
import type { DraftEntry, PlayerStat, TournamentDraft } from "@/lib/tournament/insights-query";
import { cn } from "@/lib/utils";
import type { Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";

import { useTournamentInsights } from "../../_hooks/useTournamentInsights";
import { useTournamentRoster, type RosterEntry } from "../useTournamentRoster";
import { wideOnly } from "./OverviewCards";
import { SortableTable, type SortableColumn } from "./SortableTable";

type DraftSlot =
  { kind: "captain"; position: number } | { kind: "pick"; pick: DraftEntry } | { kind: "sub" };

/** A team's strength rank by average SR against its final place; positive `delta` beat the draft's odds. */
type TeamDelta = { team: Team; srRank: number; delta: number };

type ParticipantRow = {
  entry: RosterEntry;
  slot: DraftSlot;
  performance: PlayerStat | undefined;
  /** Positive: played better than the pick slot promised (pick percentile minus performance percentile). */
  value: number | null;
};

/** A finished tournament's participants: who went where in the draft, and how it paid off. */
export function FinishedParticipantsView({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail");
  const roster = useTournamentRoster(tournament);
  const insights = useTournamentInsights(tournament);
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;
  const format = useFormatter();
  const [filter, setFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const draft = insights.draft;

  const rows = useMemo<ParticipantRow[]>(() => {
    const pickOf = new Map((draft?.picks ?? []).map((pick) => [pick.userId, pick]));
    const captainOf = new Map((draft?.captains ?? []).map((captain) => [captain.userId, captain]));
    const picked = draft?.picks.length ?? 0;
    return [...roster.byUser.values()].map((entry) => {
      const userId = entry.player.user_id;
      const captain = captainOf.get(userId);
      const pick = pickOf.get(userId);
      const slot: DraftSlot = captain
        ? { kind: "captain", position: captain.position }
        : pick
          ? { kind: "pick", pick }
          : { kind: "sub" };
      const performance = insights.players[userId]?.performance;
      const value =
        pick && performance && picked > 0 && insights.playersTotal > 0
          ? pick.overall / picked - performance.rank / insights.playersTotal
          : null;
      return { entry, slot, performance, value };
    });
  }, [roster.byUser, draft, insights.players, insights.playersTotal]);

  const needle = query.trim().toLowerCase();
  const visible = rows.filter((row) => {
    const matches =
      filter === "all" ||
      (filter === "captains" && row.slot.kind === "captain") ||
      (filter === "subs" && row.slot.kind === "sub") ||
      (row.slot.kind === "pick" && filter === `r${row.slot.pick.round}`);
    return (
      matches &&
      (needle === "" ||
        row.entry.player.name.toLowerCase().includes(needle) ||
        row.entry.team.name.toLowerCase().includes(needle))
    );
  });

  const two = (value: number) =>
    format.number(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const columns: SortableColumn<ParticipantRow>[] = [
    {
      key: "pick",
      label: t("participants.results.draft"),
      ascendingFirst: true,
      sortValue: (row) =>
        row.slot.kind === "captain" ? 0 : row.slot.kind === "pick" ? row.slot.pick.overall : 9999,
      cell: (row) =>
        row.slot.kind === "captain" ? (
          <span className="inline-flex items-center gap-1.5">
            <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
            {t("participants.results.captain")}
          </span>
        ) : row.slot.kind === "pick" ? (
          <span>
            {t("common.round", { round: row.slot.pick.round })}
            <span className="block text-label text-[color:var(--aqt-fg-dim)]">
              {row.slot.pick.autopick
                ? t("participants.results.pickAuto", { overall: row.slot.pick.overall })
                : t("participants.results.pick", { overall: row.slot.pick.overall })}
            </span>
          </span>
        ) : (
          <span className="text-[color:var(--aqt-fg-dim)]">{t("participants.results.sub")}</span>
        )
    },
    {
      key: "player",
      label: t("stats.players.player"),
      ascendingFirst: true,
      sortValue: (row) => row.entry.player.name.toLowerCase(),
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2.5">
          <PlayerRoleIcon role={row.entry.player.role} ontology={ontology} size={16} decorative />
          <PlayerName player={row.entry.player} className="max-w-[14rem] text-caption" />
        </span>
      )
    },
    {
      key: "rank",
      label: t("participants.results.rank"),
      numeric: true,
      sortValue: (row) => row.entry.player.rank,
      cell: (row) => (
        <span className="inline-flex items-center justify-end gap-2">
          {row.entry.player.rank != null ? format.number(row.entry.player.rank) : "—"}
          <DivisionIcon
            division={row.entry.player.division}
            tournamentGrid={tournament.division_grid_version}
            discipline={tournament.discipline}
            width={22}
            height={22}
            tooltip
          />
        </span>
      )
    },
    {
      key: "team",
      label: t("participants.results.team"),
      ascendingFirst: true,
      sortValue: (row) => row.entry.team.placement,
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2">
          <PlaceBadge place={row.entry.team.placement} />
          <TeamName team={row.entry.team} size="xs" className="max-w-[12rem]" />
        </span>
      )
    },
    {
      key: "performance",
      label: t("stats.metrics.performance.short"),
      title: t("stats.performanceHint"),
      numeric: true,
      ascendingFirst: true,
      sortValue: (row) => row.performance?.value ?? null,
      cell: (row) =>
        row.performance ? (
          <span>
            {two(row.performance.value)}
            <span className="block text-label text-[color:var(--aqt-fg-dim)]">
              #{row.performance.rank}
            </span>
          </span>
        ) : (
          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
        )
    },
    {
      key: "value",
      label: t("participants.results.vsPick"),
      title: t("participants.results.vsPickTitle"),
      sortValue: (row) => row.value,
      cell: (row) =>
        row.value == null ? (
          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
        ) : row.value >= 0.25 ? (
          <span className="font-semibold text-[color:var(--aqt-emerald)]">
            {t("participants.results.better")}
          </span>
        ) : row.value <= -0.25 ? (
          <span className="text-[color:var(--aqt-rose)]">{t("participants.results.worse")}</span>
        ) : (
          <span className="text-[color:var(--aqt-fg-muted)]">{t("participants.results.even")}</span>
        )
    }
  ];

  const count = (kind: "captain" | "sub") => rows.filter((row) => row.slot.kind === kind).length;
  const rounds = Array.from({ length: draft?.rounds ?? 0 }, (_, index) => index + 1);

  return (
    <section
      className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0"
      aria-label={t("participants.results.section")}
    >
      {draft ? (
        <DraftSummary rows={rows} teams={roster.teams} rounds={rounds} draft={draft} two={two} />
      ) : null}
      <CardSurface
        title={t("participants.results.all")}
        subtitle={t("common.shownOf", { shown: visible.length, total: rows.length })}
        flush
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-[color:var(--aqt-border)] px-4.5 py-3">
          <FilterChipGroup label={t("participants.results.filter")}>
            <FilterChip
              active={filter === "all"}
              onClick={() => setFilter("all")}
              count={rows.length}
            >
              {t("participants.results.everyone")}
            </FilterChip>
            {draft ? (
              <FilterChip
                active={filter === "captains"}
                onClick={() => setFilter("captains")}
                count={count("captain")}
              >
                {t("participants.results.captains")}
              </FilterChip>
            ) : null}
            {rounds.map((round) => (
              <FilterChip
                key={round}
                active={filter === `r${round}`}
                onClick={() => setFilter(`r${round}`)}
              >
                {t("common.round", { round })}
              </FilterChip>
            ))}
            {count("sub") > 0 ? (
              <FilterChip
                active={filter === "subs"}
                onClick={() => setFilter("subs")}
                count={count("sub")}
              >
                {t("participants.results.subs")}
              </FilterChip>
            ) : null}
          </FilterChipGroup>
          <SearchField
            label={t("participants.results.search")}
            placeholder={t("stats.players.searchPlaceholder")}
            value={query}
            onValueChange={setQuery}
            containerClassName="w-full sm:ms-auto sm:w-64"
          />
        </div>
        <SortableTable
          rows={visible}
          columns={columns}
          rowKey={(row) => row.entry.player.id}
          defaultSort={{ key: "pick", ascending: true }}
          label={t("participants.results.table")}
          empty={t("participants.results.empty")}
        />
        <p className="border-t border-[color:var(--aqt-border)] px-4.5 py-3 text-label text-[color:var(--aqt-fg-dim)]">
          {t("participants.results.footnote")}
        </p>
      </CardSurface>
    </section>
  );
}

function DraftSummary({
  rows,
  teams,
  rounds,
  draft,
  two
}: Readonly<{
  rows: readonly ParticipantRow[];
  teams: readonly Team[];
  rounds: readonly number[];
  draft: TournamentDraft;
  two: (value: number) => string;
}>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const autopicks = draft.picks.filter((pick) => pick.autopick).length;
  // A captain who dropped out before the event is in the draft but not in the rosters.
  const playedCaptains = rows.filter((row) => row.slot.kind === "captain").length;
  // Strength rank by average SR against the final place: who the draft favoured, and who beat it.
  const bySr = [...teams].sort((a, b) => b.avg_sr - a.avg_sr);
  const deltas: TeamDelta[] = teams
    .filter((team) => team.placement != null)
    .map((team) => ({
      team,
      srRank: bySr.indexOf(team) + 1,
      delta: bySr.indexOf(team) + 1 - (team.placement as number)
    }));
  const over = [...deltas].sort((a, b) => b.delta - a.delta).slice(0, 3);
  const under = [...deltas].sort((a, b) => a.delta - b.delta).slice(0, 3);
  // How even the draft left the field: the average team and the gap between the strongest and the weakest.
  const srs = teams.map((team) => team.avg_sr).filter((sr) => sr > 0);
  const srOf = (value: number) => format.number(Math.round(value));
  const bestOf = (predicate: (row: ParticipantRow) => boolean) =>
    rows
      .filter((row) => predicate(row) && row.performance)
      .sort((a, b) => (a.performance?.value ?? 99) - (b.performance?.value ?? 99))[0];
  const steals = [
    {
      label: t("participants.results.captains"),
      row: bestOf((row) => row.slot.kind === "captain")
    },
    ...rounds.map((round) => ({
      label: t("common.round", { round }),
      row: bestOf((row) => row.slot.kind === "pick" && row.slot.pick.round === round)
    }))
  ].filter((item) => item.row);

  const teamLine = ({ team, srRank, delta }: TeamDelta) => (
    <li key={team.id} className="flex items-center justify-between gap-3">
      <TeamName team={team} size="xs" className="min-w-0 text-caption" />
      <span className="aqt-tnum shrink-0 text-label text-[color:var(--aqt-fg-dim)]">
        SR #{srRank} →{" "}
        <span className="font-semibold text-[color:var(--aqt-fg)]">{team.placement}</span>
        <span
          className={cn(
            "ms-1.5",
            delta > 0 ? "text-[color:var(--aqt-emerald)]" : "text-[color:var(--aqt-rose)]"
          )}
        >
          {delta > 0 ? `+${delta}` : delta}
        </span>
      </span>
    </li>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <CardSurface title={t("overview.draftCard.title")}>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5">
          <ProfileStat
            label={t("participants.results.captainsCount")}
            value={draft.captains.length}
            sub={
              playedCaptains !== draft.captains.length
                ? t("participants.results.played", { count: playedCaptains })
                : undefined
            }
            size="md"
          />
          <ProfileStat label={t("participants.results.rounds")} value={draft.rounds} size="md" />
          <ProfileStat
            label={t("participants.results.picks")}
            value={draft.picks.length}
            size="md"
          />
          <ProfileStat label={t("participants.results.autopicks")} value={autopicks} size="md" />
          {srs.length > 0 ? (
            <>
              <ProfileStat
                label={t("participants.results.avgTeamSr")}
                value={srOf(srs.reduce((sum, sr) => sum + sr, 0) / srs.length)}
                size="md"
              />
              <ProfileStat
                label={t("participants.results.srSpread")}
                value={srOf(Math.max(...srs) - Math.min(...srs))}
                sub={t("participants.results.srSpreadSub")}
                size="md"
              />
            </>
          ) : null}
        </div>
      </CardSurface>
      <CardSurface
        title={t("participants.results.strength")}
        subtitle={wideOnly(t("participants.results.strengthSub"))}
      >
        <Eyebrow className="block">{t("participants.results.over")}</Eyebrow>
        <ul className="mt-2 grid gap-2">{over.map(teamLine)}</ul>
        <Eyebrow className="mt-4 block">{t("participants.results.under")}</Eyebrow>
        <ul className="mt-2 grid gap-2">{under.map(teamLine)}</ul>
      </CardSurface>
      <CardSurface
        title={t("participants.results.bestByRound")}
        subtitle={wideOnly(t("participants.results.bestByRoundSub"))}
      >
        <ol className="grid gap-2.5">
          {steals.map(({ label, row }) =>
            row ? (
              <li
                key={label}
                className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-center gap-2"
              >
                <span className="text-label text-[color:var(--aqt-fg-muted)]">{label}</span>
                <span className="min-w-0">
                  <PlayerName player={row.entry.player} className="text-caption" />
                  <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                    {row.entry.team.name}
                  </span>
                </span>
                <span className="aqt-tnum text-caption font-semibold">
                  {row.performance ? two(row.performance.value) : "—"}
                </span>
              </li>
            ) : null
          )}
        </ol>
      </CardSurface>
    </div>
  );
}
