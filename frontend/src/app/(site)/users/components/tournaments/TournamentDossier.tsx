"use client";

import React from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { tournamentHref } from "@/lib/tournament/url";
import { Trophy } from "lucide-react";
import { useTranslations } from "next-intl";
import { canonicalDisplay } from "@/lib/player";
import type { UserTournamentEntry } from "@/types/user.types";
import { TournamentTeamTable } from "@/components/TournamentTeamCard";
import ProfileWidget from "@/components/profile/ProfileWidget";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import EncounterRow from "@/app/(site)/users/components/tournaments/EncounterRow";
import {
  SummaryStrip,
  WdlText,
  type SummaryCell
} from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";
import {
  groupEncountersByStage,
  mapsWinratePct,
  placementMedal,
  tournamentAggregate,
  winrateColor
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

interface Props {
  tournament: UserTournamentEntry | null;
  selfUserId: number;
  /** True while the selected event's encounters are still being fetched
   *  lazily (see TournamentsHistory) — shows a run-section skeleton instead
   *  of a misleading "no run recorded" flash. */
  loadingEncounters?: boolean;
}

const MEDAL_COLOR: Record<string, string> = {
  gold: "var(--aqt-gold)",
  silver: "var(--aqt-silver)",
  bronze: "var(--aqt-bronze)",
  none: "var(--aqt-fg)"
};

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <Eyebrow as="div" className="mb-2.5 aqt-tnum">
    {children}
  </Eyebrow>
);

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
            <span className="text-label font-normal text-[color:var(--aqt-fg-faint)]">
              {" "}
              / {args.countTeams}
            </span>
          ) : null}
        </>
      )
    },
    {
      key: "record",
      label: t("users.tournaments.dossier.summary.record"),
      value: <WdlText won={args.won} lost={args.lost} draw={args.draw} className="text-ui" />
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
    }
  ];
};

/** The game module's own trailing summary cell (Overwatch: average MVP placement), drawn in the entries' game. */
const ModuleSummaryCell = ({ entries }: { entries: UserTournamentEntry[] }) => (
  <ProfileWidget
    axis={entries[0].workspace_id}
    discipline={entries[0].discipline}
    slot="tournamentSummary"
    props={{ entries }}
    fallback={null}
  />
);

/** Roster table + per-stage "run" for one tournament entry. */
const EventBody = ({
  t,
  selfUserId,
  loadingEncounters
}: {
  t: UserTournamentEntry;
  selfUserId: number;
  loadingEncounters?: boolean;
}) => {
  const tr = useTranslations();
  // The roster is drawn in the tournament's own game, whatever game the profile browses.
  const ontology = useDisciplineMetadata(t.workspace_id, t.discipline).data ?? null;
  const stages = groupEncountersByStage(t, selfUserId);
  const hasEncounters = t.encounters.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <SectionLabel>{tr("users.tournaments.roster.title")}</SectionLabel>
        <TournamentTeamTable
          players={(t.players ?? []).map((player) => ({ ...player, display: canonicalDisplay(player.name) }))}
          tournamentGrid={t.division_grid_version}
          discipline={t.discipline}
          ontology={ontology}
          highlightUserId={selfUserId}
        />
      </div>
      <div>
        <SectionLabel>{tr("users.tournaments.dossier.run")}</SectionLabel>
        {loadingEncounters ? (
          // Skeleton while TournamentsHistory's lazy fetch is in flight —
          // avoids a misleading "no run recorded" flash on every selection.
          <div className="flex flex-col gap-1.5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : hasEncounters ? (
          <div className="divide-y divide-[color:var(--aqt-border)]">
            {stages.map((stage) => (
              <div key={stage.key} className="py-2 first:pt-0 last:pb-0">
                <div className="flex items-center justify-between gap-2 py-1">
                  <Eyebrow tone="muted" className="aqt-tnum">
                    {stage.name}
                  </Eyebrow>
                  <WdlText
                    won={stage.won}
                    lost={stage.lost}
                    draw={stage.drawn}
                    className="text-label"
                  />
                </div>
                {stage.encounters.map((enc) => (
                  <EncounterRow key={enc.id} enc={enc} selfUserId={selfUserId} teamId={t.team_id} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="py-6 text-center text-caption text-[color:var(--aqt-fg-muted)]">
            {tr("users.tournaments.dossier.noRun")}
          </div>
        )}
      </div>
    </div>
  );
};

const SingleDossier = ({
  t,
  selfUserId,
  loadingEncounters
}: {
  t: UserTournamentEntry;
  selfUserId: number;
  loadingEncounters?: boolean;
}) => {
  const tr = useTranslations();
  const ontology = useDisciplineMetadata(t.workspace_id, t.discipline).data ?? null;
  const agg = tournamentAggregate(t);
  const cells = summaryCells(tr, {
    placement: t.placement ?? null,
    countTeams: t.count_teams ?? null,
    won: agg.won,
    lost: agg.lost,
    draw: agg.draw,
    mapsWon: agg.mapsWon,
    mapsLost: agg.mapsLost,
    closeness: t.closeness ?? null
  });

  return (
    <Card className="overflow-hidden">
      <div className="p-4">
        <div className="flex items-start gap-3.5">
          <PlaceBadge place={t.placement ?? null} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <HoverPrefetchLink
                href={tournamentHref(t.id)}
                className="aqt-display text-title font-bold leading-tight text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
              >
                {t.name}
              </HoverPrefetchLink>
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
              <PlayerRoleIcon role={t.role} ontology={ontology} size={15} />
              <span className="aqt-tnum truncate">
                {tr("users.tournaments.teamName", { name: String(t.team) })}
              </span>
              <DivisionIcon
                division={t.division}
                tournamentGrid={t.division_grid_version}
                width={20}
                height={20}
              />
            </div>
          </div>
        </div>
      </div>
      <SummaryStrip cells={cells} extra={<ModuleSummaryCell entries={[t]} />} />
      <div className="p-4">
        <EventBody t={t} selfUserId={selfUserId} loadingEncounters={loadingEncounters} />
      </div>
    </Card>
  );
};

const TournamentDossier = ({ tournament, selfUserId, loadingEncounters }: Props) => {
  const t = useTranslations();
  if (!tournament) {
    return (
      <Card className="flex flex-col items-center justify-center gap-3 overflow-hidden px-4 py-16 text-center">
        <Trophy size={26} className="text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
        <span className="text-caption text-[color:var(--aqt-fg-muted)]">
          {t("users.tournaments.dossier.empty")}
        </span>
      </Card>
    );
  }
  return <SingleDossier t={tournament} selfUserId={selfUserId} loadingEncounters={loadingEncounters} />;
};

export default TournamentDossier;
