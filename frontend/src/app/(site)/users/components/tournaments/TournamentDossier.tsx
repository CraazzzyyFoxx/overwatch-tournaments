"use client";

import React from "react";
import Link from "next/link";
import { Crown, Trophy } from "lucide-react";
import { useTranslations } from "next-intl";
import { UserTournament } from "@/types/user.types";
import { TournamentTeamTable } from "@/components/TournamentTeamCard";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import EncounterRow from "@/app/(site)/users/components/tournaments/EncounterRow";
import {
  LeagueBadge,
  PlaceBadge,
  SummaryStrip,
  WdlText,
  type SummaryCell
} from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";
import {
  type TournamentGroup,
  avgMvpPlacement,
  divisionLabel,
  groupAggregate,
  groupBestPlacement,
  groupDisplayName,
  groupEncountersByStage,
  groupEntries,
  isLeagueGroup,
  mapsWinratePct,
  placementMedal,
  roleColorVar,
  winrateColor
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

interface Props {
  group: TournamentGroup | null;
  selfUserId: number;
}

const MEDAL_COLOR: Record<string, string> = {
  gold: "var(--aqt-gold)",
  silver: "var(--aqt-silver)",
  bronze: "var(--aqt-bronze)",
  none: "var(--aqt-fg)"
};

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2.5 aqt-mono text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
    {children}
  </div>
);

const useVerdict = (placement: number | null | undefined, countTeams: number | null | undefined) => {
  const t = useTranslations();
  if (!placement || !countTeams) return null;
  const params = { placement: String(placement), count: String(countTeams) };
  if (placement === 1) return t("users.tournaments.dossier.verdict.champion", { count: String(countTeams) });
  if (placement <= 3) return t("users.tournaments.dossier.verdict.podium", params);
  if (placement <= Math.ceil(countTeams / 2)) return t("users.tournaments.dossier.verdict.topHalf", params);
  return t("users.tournaments.dossier.verdict.group", params);
};

const Verdict = ({ text }: { text: string }) => (
  <div
    className="mx-4 mt-4 rounded-[8px] bg-[color:var(--aqt-card-2)] px-3 py-2.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]"
    style={{ borderLeft: "2px solid var(--aqt-teal)" }}
  >
    {text}
  </div>
);

const ChampionBanner = () => {
  const t = useTranslations();
  return (
    <div
      className="flex items-center gap-3 rounded-[10px] px-4 py-3"
      style={{ background: "hsl(42 63% 60% / 0.1)", border: "1px solid hsl(42 63% 60% / 0.35)" }}
    >
      <Crown size={22} style={{ color: "var(--aqt-gold)" }} aria-hidden="true" />
      <div className="min-w-0">
        <div className="aqt-display text-[15px] font-bold" style={{ color: "var(--aqt-gold)" }}>
          {t("users.tournaments.dossier.champions")}
        </div>
        <div className="aqt-mono text-[11.5px] text-[color:var(--aqt-fg-muted)]">
          {t("users.tournaments.dossier.championsSub")}
        </div>
      </div>
    </div>
  );
};

const summaryCells = (
  t: ReturnType<typeof useTranslations<never>>,
  args: {
    placement: number | null;
    countTeams: number | null;
    won: number;
    lost: number;
    draw: number;
    mapsWon: number;
    mapsLost: number;
    closeness: number | null;
    avgMvp: number | null;
  }
): SummaryCell[] => {
  const wr = mapsWinratePct(args.mapsWon, args.mapsLost);
  return [
    {
      key: "placement",
      label: t("users.tournaments.dossier.summary.placement"),
      color: MEDAL_COLOR[placementMedal(args.placement)],
      value: (
        <>
          {args.placement && args.placement > 0 ? args.placement : "—"}
          {args.countTeams ? (
            <span className="text-[12px] font-normal text-[color:var(--aqt-fg-faint)]"> / {args.countTeams}</span>
          ) : null}
        </>
      )
    },
    {
      key: "record",
      label: t("users.tournaments.dossier.summary.record"),
      value: <WdlText won={args.won} lost={args.lost} draw={args.draw} className="text-[15px]" />
    },
    {
      key: "maps",
      label: t("users.tournaments.dossier.summary.maps"),
      value: (
        <>
          <span style={{ color: "var(--aqt-emerald)" }}>{args.mapsWon}</span>
          <span className="text-[color:var(--aqt-fg-faint)]">–</span>
          <span style={{ color: "var(--aqt-rose)" }}>{args.mapsLost}</span>
        </>
      )
    },
    {
      key: "winrate",
      label: t("users.tournaments.dossier.summary.winrate"),
      color: winrateColor(wr),
      value: wr != null ? `${Math.round(wr)}%` : "—"
    },
    {
      key: "closeness",
      label: t("users.tournaments.dossier.summary.closeness"),
      value: args.closeness != null ? `${Math.round(args.closeness * 100)}%` : "—"
    },
    {
      key: "avgMvp",
      label: t("users.tournaments.dossier.summary.avgMvp"),
      value: args.avgMvp != null ? args.avgMvp.toFixed(1) : "—"
    }
  ];
};

/** Roster table + per-stage "run" for one tournament entry. */
const EventBody = ({ t, selfUserId }: { t: UserTournament; selfUserId: number }) => {
  const tr = useTranslations();
  const stages = groupEncountersByStage(t, selfUserId);
  const hasEncounters = (t.encounters ?? []).length > 0;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <SectionLabel>{tr("users.tournaments.roster.title")}</SectionLabel>
        <TournamentTeamTable
          players={t.players ?? []}
          tournamentGrid={t.division_grid_version}
          highlightUserId={selfUserId}
          youLabel={tr("users.tournaments.you")}
          avgMvpLabel={tr("users.tournaments.roster.avgMvp")}
          heroesLabel={tr("users.tournaments.roster.heroes")}
          signatureHeroesLabel={tr("users.tournaments.roster.signatureHeroes")}
        />
      </div>
      <div>
        <SectionLabel>{tr("users.tournaments.dossier.run")}</SectionLabel>
        {hasEncounters ? (
          <div className="overflow-hidden rounded-[10px] border border-[color:var(--aqt-border)]">
            {stages.map((stage) => (
              <div key={stage.key}>
                <div className="flex items-center justify-between gap-2 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-4 py-2">
                  <span className="aqt-mono text-[11px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-muted)]">
                    {stage.name}
                  </span>
                  <WdlText won={stage.won} lost={stage.lost} draw={stage.drawn} className="text-[11px]" />
                </div>
                {stage.encounters.map((enc) => (
                  <EncounterRow key={enc.id} enc={enc} selfUserId={selfUserId} teamId={t.team_id} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[10px] border border-[color:var(--aqt-border)] px-4 py-6 text-center text-[13px] text-[color:var(--aqt-fg-muted)]">
            {tr("users.tournaments.dossier.noRun")}
          </div>
        )}
      </div>
    </div>
  );
};

const SingleDossier = ({ t, selfUserId }: { t: UserTournament; selfUserId: number }) => {
  const tr = useTranslations();
  const agg = groupAggregate(t);
  const verdict = useVerdict(t.placement, t.count_teams);
  const cells = summaryCells(tr, {
    placement: t.placement ?? null,
    countTeams: t.count_teams ?? null,
    won: agg.won,
    lost: agg.lost,
    draw: agg.draw,
    mapsWon: agg.mapsWon,
    mapsLost: agg.mapsLost,
    closeness: t.closeness ?? null,
    avgMvp: avgMvpPlacement([t])
  });

  return (
    <div className="aqt-card-surface">
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-start gap-3.5">
          <PlaceBadge placement={t.placement ?? null} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/tournaments/${t.id}`}
                className="aqt-display text-[22px] font-bold leading-tight text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
              >
                {t.name}
              </Link>
              {t.is_league ? <LeagueBadge>{tr("users.tournaments.leagueBadge")}</LeagueBadge> : null}
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-[12.5px] text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex" title={t.role ?? undefined}>
                <PlayerRoleIcon role={t.role} size={15} color={roleColorVar(t.role)} />
              </span>
              <span className="aqt-mono truncate">{tr("users.tournaments.teamName", { name: String(t.team) })}</span>
              <DivisionIcon division={t.division} tournamentGrid={t.division_grid_version} width={20} height={20} />
            </div>
          </div>
        </div>
        {t.placement === 1 ? <ChampionBanner /> : null}
      </div>
      <SummaryStrip cells={cells} />
      {verdict ? <Verdict text={verdict} /> : null}
      <EventBody t={t} selfUserId={selfUserId} />
    </div>
  );
};

const DivisionHeader = ({ t }: { t: UserTournament }) => {
  const tr = useTranslations();
  const agg = groupAggregate(t);
  return (
    <div className="flex items-center gap-3 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-4 py-2.5">
      <DivisionIcon division={t.division} tournamentGrid={t.division_grid_version} width={28} height={28} />
      <Link
        href={`/tournaments/${t.id}`}
        className="min-w-0 flex-1 truncate text-[14px] font-semibold text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
      >
        {divisionLabel(t)}
      </Link>
      <PlaceBadge placement={t.placement ?? null} size="sm" />
      <WdlText won={agg.won} lost={agg.lost} draw={agg.draw} className="text-[12px]" />
    </div>
  );
};

const LeagueDossier = ({ entries, selfUserId }: { entries: UserTournament[]; selfUserId: number }) => {
  const tr = useTranslations();
  const agg = entries.reduce(
    (acc, t) => {
      const a = groupAggregate(t);
      return {
        won: acc.won + a.won,
        lost: acc.lost + a.lost,
        draw: acc.draw + a.draw,
        mapsWon: acc.mapsWon + a.mapsWon,
        mapsLost: acc.mapsLost + a.mapsLost
      };
    },
    { won: 0, lost: 0, draw: 0, mapsWon: 0, mapsLost: 0 }
  );
  const best = groupBestPlacement(entries);
  const bestEntry = entries.find((t) => t.placement === best) ?? entries[0];
  const closenessValues = entries.map((t) => t.closeness).filter((c): c is number => typeof c === "number");
  const avgCloseness = closenessValues.length
    ? closenessValues.reduce((sum, c) => sum + c, 0) / closenessValues.length
    : null;
  const verdict = useVerdict(best, bestEntry.count_teams);
  const isChampion = entries.some((t) => t.placement === 1);

  const cells = summaryCells(tr, {
    placement: best,
    countTeams: bestEntry.count_teams ?? null,
    won: agg.won,
    lost: agg.lost,
    draw: agg.draw,
    mapsWon: agg.mapsWon,
    mapsLost: agg.mapsLost,
    closeness: avgCloseness,
    avgMvp: avgMvpPlacement(entries)
  });

  return (
    <div className="aqt-card-surface">
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-start gap-3.5">
          <PlaceBadge placement={best} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="aqt-display text-[22px] font-bold leading-tight text-[color:var(--aqt-fg)]">
                {groupDisplayName(entries)}
              </span>
              <LeagueBadge>{tr("users.tournaments.leagueBadge")}</LeagueBadge>
            </div>
            <div className="mt-1.5 aqt-mono text-[12.5px] text-[color:var(--aqt-fg-muted)]">
              {tr("users.tournaments.divisionsCount", { count: String(entries.length) })}
            </div>
          </div>
        </div>
        {isChampion ? <ChampionBanner /> : null}
      </div>
      <SummaryStrip cells={cells} />
      {verdict ? <Verdict text={verdict} /> : null}
      <div className="flex flex-col gap-4 p-4">
        <SectionLabel>{tr("users.tournaments.dossier.divisions")}</SectionLabel>
        {entries.map((t) => (
          <div key={t.id} className="overflow-hidden rounded-[10px] border border-[color:var(--aqt-border)]">
            <DivisionHeader t={t} />
            <EventBody t={t} selfUserId={selfUserId} />
          </div>
        ))}
      </div>
    </div>
  );
};

const TournamentDossier = ({ group, selfUserId }: Props) => {
  const t = useTranslations();
  if (!group) {
    return (
      <div className="aqt-card-surface flex flex-col items-center justify-center gap-3 px-4 py-16 text-center">
        <Trophy size={26} className="text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
        <span className="text-[13px] text-[color:var(--aqt-fg-muted)]">{t("users.tournaments.dossier.empty")}</span>
      </div>
    );
  }
  if (isLeagueGroup(group)) {
    return <LeagueDossier entries={groupEntries(group)} selfUserId={selfUserId} />;
  }
  return <SingleDossier t={group} selfUserId={selfUserId} />;
};

export default TournamentDossier;
