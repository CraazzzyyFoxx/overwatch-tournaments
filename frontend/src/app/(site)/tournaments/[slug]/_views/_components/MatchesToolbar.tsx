"use client";

import { CalendarClock, ListOrdered } from "lucide-react";
import { useTranslations } from "next-intl";

import { FilterChip } from "@/components/ui/filter-chip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

import { SectionToolbar } from "../../_components/SectionToolbar";
import { ViewSegment } from "../../_components/ViewSegment";
import { stageKey, type MatchesView, type StageMeta } from "../tournamentMatches.model";

type MatchesToolbarProps = {
  /** Stage buckets of the encounters that survived the team/map filters. */
  stages: StageMeta[];
  stageFilter: string | null;
  /** How many encounters each chip would show, keyed by `stageKey`. */
  stageCounts: Map<string, number>;
  totalCount: number;
  /** The `time` segment exists only once the organizer has scheduled something. */
  hasSchedule: boolean;
  teamFilter: number | null;
  teamName: string | null;
  teamOptions: { id: number; name: string }[];
  mapFilter: number | null;
  mapName: string | null;
  setParams: (params: Record<string, string | null>) => void;
};

/**
 * The matches section's filter row: stage chips, the team picker (and the
 * removable chip it becomes), the deep-linked map chip, and the round/time
 * segment.
 */
export function MatchesToolbar({
  stages,
  stageFilter,
  stageCounts,
  totalCount,
  hasSchedule,
  teamFilter,
  teamName,
  teamOptions,
  mapFilter,
  mapName,
  setParams
}: Readonly<MatchesToolbarProps>) {
  const t = useTranslations();

  return (
    <SectionToolbar
      label={t("tournamentDetail.matches.toolbarLabel")}
      end={
        hasSchedule ? (
          <ViewSegment<MatchesView>
            param="view"
            defaultValue="round"
            label={t("tournamentDetail.matches.viewLabel")}
            options={[
              {
                value: "round",
                label: <ListOrdered aria-hidden width={14} height={14} />,
                ariaLabel: t("tournamentDetail.matches.viewRound")
              },
              {
                value: "time",
                label: <CalendarClock aria-hidden width={14} height={14} />,
                ariaLabel: t("tournamentDetail.matches.viewTime")
              }
            ]}
          />
        ) : undefined
      }
    >
      {/* One stage is no choice: the chips appear only where they filter. */}
      {stages.length > 1 ? (
        <>
          <FilterChip
            active={stageFilter === null}
            count={totalCount}
            onClick={() => setParams({ stage: null })}
          >
            {t("tournamentDetail.matches.allStages")}
          </FilterChip>
          {stages.map((stage) => (
            <FilterChip
              key={stageKey(stage.id)}
              active={stageFilter === stageKey(stage.id)}
              count={stageCounts.get(stageKey(stage.id)) ?? 0}
              onClick={() => setParams({ stage: stageKey(stage.id) })}
            >
              {stage.name || t("common.stage")}
            </FilterChip>
          ))}
        </>
      ) : null}
      {teamFilter !== null ? (
        <FilterChip
          active
          aria-label={t("tournamentDetail.matches.clearTeamFilter")}
          onClick={() => setParams({ team: null })}
        >
          {t("tournamentDetail.matches.teamFilter", {
            name: teamName ?? String(teamFilter)
          })}
          <span aria-hidden>×</span>
        </FilterChip>
      ) : teamOptions.length > 0 ? (
        /* Wireframe §7 ②: one "+ Team" chip, not a filter panel. The
           picker lists every team that played, and the chosen team
           becomes the removable chip above. */
        <Select value="" onValueChange={(value) => setParams({ team: value })}>
          <SelectTrigger
            aria-label={t("tournamentDetail.matches.pickTeam")}
            className="filter-sort h-8 w-auto gap-1.5 shadow-none focus:ring-0 focus:ring-offset-0"
          >
            <SelectValue placeholder={t("tournamentDetail.matches.addTeam")} />
          </SelectTrigger>
          <SelectContent>
            {teamOptions.map((team) => (
              <SelectItem key={team.id} value={String(team.id)}>
                {team.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
      {mapFilter !== null ? (
        <FilterChip
          active
          aria-label={t("tournamentDetail.matches.clearMapFilter")}
          onClick={() => setParams({ map: null })}
        >
          {t("tournamentDetail.matches.mapFilter", { name: mapName ?? String(mapFilter) })}
          <span aria-hidden>×</span>
        </FilterChip>
      ) : null}
    </SectionToolbar>
  );
}
