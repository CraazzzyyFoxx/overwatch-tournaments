"use client";

import { useMemo } from "react";
import { ArrowRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import TeamName from "@/components/TeamName";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { useFormatter } from "@/lib/datetime/client";
import { sortTeamPlayers } from "@/lib/player";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { StandingsDistribution } from "@/types/analytics.types";
import { formatPlace } from "@/disciplines/overwatch/analytics/analytics.helpers";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";
import type { TeamVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";

import DeltaText from "../DeltaText";
import InfoDot from "../InfoDot";
import RosterRow from "./RosterRow";

interface TeamDetailProps {
  team: TeamVM;
  /** Monte-Carlo distribution for this team (organizer-only; woven into the detail). */
  distribution?: StandingsDistribution;
  /** The tournament's own role dictionary (its game's metadata): roster order and role glyphs. */
  ontology: RoleOntology;
  /** The bracket has several groups, so the header names this team's. */
  showGroup: boolean;
  onSelectPlayer: (playerId: number) => void;
  onExplain: (term: GlossaryTerm) => void;
}

/** The organizer's Monte-Carlo read: the three probabilities as facts, the finishing-place histogram under them. */
function MonteCarlo({ distribution }: Readonly<{ distribution: StandingsDistribution }>) {
  const t = useTranslations();
  const format = useFormatter();
  const bars = useMemo(() => {
    const entries = Object.entries(distribution.position_histogram)
      .map(([pos, count]) => ({ pos: Number(pos), count }))
      .sort((a, b) => a.pos - b.pos);
    const max = entries.reduce((m, e) => Math.max(m, e.count), 0) || 1;
    return entries.map((e) => ({ ...e, height: Math.max(6, (e.count / max) * 100) }));
  }, [distribution.position_histogram]);
  const percent = (value: number) => format.number(value, { style: "percent", maximumFractionDigits: 0 });

  return (
    <section className="border-t border-[color:var(--aqt-border)] px-4 py-3">
      <Eyebrow as="h3">{t("analytics.distribution.title")}</Eyebrow>
      <dl className="mt-2 grid grid-cols-3 gap-3">
        {(
          [
            ["top1", distribution.prob_top1],
            ["top3", distribution.prob_top3],
            ["top8", distribution.prob_top8]
          ] as const
        ).map(([key, value]) => (
          <div key={key}>
            <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{t(`analytics.distribution.${key}`)}</dt>
            <dd className="aqt-tnum text-ui font-semibold text-[color:var(--aqt-fg)]">{percent(value)}</dd>
          </div>
        ))}
      </dl>
      {/* The probabilities above are its text; the shape is the extra a sighted reader gets. */}
      <div aria-hidden className="mt-3 flex h-10 items-end gap-px">
        {bars.map((bar) => (
          <span
            key={bar.pos}
            className="flex-1 rounded-t-sm bg-[color:color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]"
            style={{ height: `${bar.height}%` }}
            title={`#${bar.pos}: ${bar.count}`}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * Team drill-down as one card: place, name and delta in the header, the
 * predicted → finished line, the organizer's Monte-Carlo read, then the roster
 * (each player opens the player panel).
 */
export default function TeamDetail({
  team,
  distribution,
  ontology,
  showGroup,
  onSelectPlayer,
  onExplain
}: Readonly<TeamDetailProps>) {
  const t = useTranslations();
  const locale = useLocale() as "en" | "ru";
  const tournamentGrid = team.tournament?.division_grid_version;
  const players = useMemo(() => sortTeamPlayers(team.players, ontology), [team.players, ontology]);
  const record = `${team.wins}–${team.losses}`;

  return (
    <Card className="overflow-hidden">
      <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <Eyebrow as="p" className="aqt-tnum">
            {showGroup && team.group?.name
              ? t("analytics.community.team.groupRecord", {
                  group: team.group.name,
                  wins: team.wins,
                  losses: team.losses
                })
              : record}
          </Eyebrow>
          <h2 className="mt-1.5 flex min-w-0 items-baseline gap-2.5">
            {team.placement != null ? (
              <span className="aqt-tnum shrink-0 font-onest text-title font-semibold text-[color:var(--aqt-fg)]">
                {formatPlace(team.placement, locale)}
              </span>
            ) : null}
            <TeamName team={team} size="sm" nameClassName="text-heading font-semibold text-[color:var(--aqt-fg)]" />
          </h2>
        </div>
        <DeltaText delta={team.placement_delta} className="mt-0.5 shrink-0" />
      </header>

      {team.predicted_place != null ? (
        <p className="flex flex-wrap items-center gap-1.5 px-4 pb-3 text-caption text-[color:var(--aqt-fg-muted)]">
          {t("analytics.community.team.predictedShort", { place: formatPlace(team.predicted_place, locale) })}
          {team.placement != null ? (
            <>
              <ArrowRight aria-hidden className="size-3.5 text-[color:var(--aqt-fg-dim)]" />
              {t("analytics.community.team.finishedShort", { place: formatPlace(team.placement, locale) })}
            </>
          ) : null}
          <InfoDot term="predicted_move" onExplain={onExplain} />
        </p>
      ) : null}

      {distribution ? <MonteCarlo distribution={distribution} /> : null}

      <section className="border-t border-[color:var(--aqt-border)]">
        <Eyebrow as="h3" className="px-4 pt-3 pb-1">
          {t("analytics.community.team.rosterCount", { count: players.length })}
        </Eyebrow>
        <ul className="divide-y divide-[color:var(--aqt-border)]">
          {players.map((player) => (
            <li key={player.id}>
              <RosterRow
                player={player}
                tournamentGrid={tournamentGrid}
                ontology={ontology}
                onSelect={() => onSelectPlayer(player.id)}
              />
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}
