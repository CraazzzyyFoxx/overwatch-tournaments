"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { EYEBROW_CLASS, TONE_TEXT } from "@/components/kit/tone";
import { BracketView, type BracketSlotRef } from "@/components/bracket/BracketView";
import type { BracketMatch } from "@/lib/bracket/view";
import { notify } from "@/lib/notify";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { StageBracketPreviewMatch } from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import type { Stage } from "@/types/tournament.types";

import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { useHubEncountersQuery } from "../../hubQueries";
import { BRACKET_STAGE_TYPES, type BracketTeamCountSource, type StageProjection } from "@/lib/bracket/projection";

const COUNT_SOURCE_NOTE: Record<BracketTeamCountSource, string> = {
  seeded: "from the teams already seeded into this stage",
  slots: "from the empty slots wired into this stage",
  projected: "projected from the preceding group stage's advancing count",
  unknown: "no seeds, slots or upstream group stage yet — depth falls back to Swiss max rounds"
};

/**
 * The generator's skeleton as the bracket view reads it.
 *
 * `local_id` becomes the match id, and each source edge points at another row's
 * `local_id`, so the view's own slot hints ("W M3") come out of the real
 * advancement edges rather than a shape guessed from round numbers.
 */
function toBracketMatches(
  rows: StageBracketPreviewMatch[],
  teamById: Map<number, Team>
): BracketMatch[] {
  return rows.map((row) => ({
    id: row.local_id,
    name: row.name,
    round: row.round,
    status: "open",
    score: { home: 0, away: 0 },
    best_of: row.best_of,
    home_team_id: row.home_team_id ?? 0,
    away_team_id: row.away_team_id ?? 0,
    home_team: row.home_team_id == null ? null : (teamById.get(row.home_team_id) ?? null),
    away_team: row.away_team_id == null ? null : (teamById.get(row.away_team_id) ?? null),
    sources: row.sources.map((source) => ({
      encounter_id: source.local_id,
      role: source.role,
      slot: source.slot
    }))
  }));
}

/**
 * The stage as it would be generated right now — read only.
 *
 * The bracket itself is the real tree, drawn by the same `BracketView` the
 * public page uses: once the stage has matches it draws those (scores, live
 * state and all), and before that it draws the skeleton the backend generator
 * would produce (`GET /admin/stages/{id}/bracket-preview`). Neither is a
 * bracket-shaped drawing re-derived here, which is the only way the preview and
 * the generated bracket cannot disagree about byes and lower-bracket drops.
 *
 * The per-round best-of is on the cards themselves ("Bo3"), so the round chips
 * this section used to list beside them are gone. The drawn tree follows the
 * SAVED stage — a format or best-of edit shows up once it is saved.
 *
 * Matches are NOT editable here. Editing them is the Matches tab's job, and
 * the Items section carries the cross-link.
 */
export function BracketPreview({
  projection,
  stage,
  teams,
  className
}: Readonly<{
  projection: StageProjection;
  stage: Stage;
  teams: Team[];
  className?: string;
}>) {
  const { bracketTeams, unresolved } = projection;

  // The hub's shared encounters query: the same cache entry the Matches tab
  // observes, so this costs nothing extra there and stays invalidated by every
  // workspace mutation.
  const encountersQuery = useHubEncountersQuery(stage.tournament_id);
  const generated = useMemo(
    () => (encountersQuery.data?.results ?? []).filter((encounter) => encounter.stage_id === stage.id),
    [encountersQuery.data, stage.id]
  );

  const isBracket = BRACKET_STAGE_TYPES.includes(stage.stage_type);
  const previewQuery = useQuery({
    // The whole stage in the key: the skeleton is a function of the SAVED stage,
    // so any save that changes its seeds, format or best-of refetches it.
    queryKey: ["admin", "stage", stage.id, "bracket-preview", stage],
    queryFn: () => adminService.getStageBracketPreview(stage.id),
    // A group stage has no bracket to project, so it never asks.
    enabled: isBracket && !encountersQuery.isPending && generated.length === 0
  });

  const teamById = useMemo(() => new Map(teams.map((team) => [team.id, team])), [teams]);
  const projected = useMemo(
    () => toBracketMatches(previewQuery.data ?? [], teamById),
    [previewQuery.data, teamById]
  );

  const matches: BracketMatch[] = generated.length > 0 ? generated : projected;
  const isLoading = encountersQuery.isPending || (previewQuery.isPending && previewQuery.isFetching);

  // Generated matches are real rows, so their slots can be rearranged from
  // here as well as from the public bracket; a projection has nothing to write.
  const queryClient = useQueryClient();
  const swapSlots = useCallback(
    async (source: BracketSlotRef, target: BracketSlotRef) => {
      try {
        await adminService.swapEncounterSlot(source.encounter.id, {
          slot: source.slot,
          target_encounter_id: target.encounter.id,
          target_slot: target.slot
        });
        notify.success("Teams swapped");
      } catch (error) {
        notify.apiError(error, { title: "Could not swap teams" });
      }
      invalidateTournamentWorkspace(queryClient, stage.tournament_id);
    },
    [queryClient, stage.tournament_id]
  );
  const onSwapSlots = generated.length > 0 ? swapSlots : undefined;

  // A group stage's matches otherwise land in one flat "Round 1" column:
  // `BracketView` draws rounds, not groups, so Group A and Group B interleave
  // with nothing saying which is which. Split by stage item — one tree per
  // group — whenever the stage really has more than one.
  const groupSections = useMemo(() => {
    if (!projection.isGroups || stage.items.length < 2) return null;
    const itemIds = new Set(stage.items.map((item) => item.id));
    const sections = [...stage.items]
      .sort((left, right) => left.order - right.order)
      .map((item) => ({
        key: item.id,
        label: item.name,
        matches: matches.filter((match) => match.stage_item_id === item.id)
      }))
      .filter((section) => section.matches.length > 0);
    const loose = matches.filter(
      (match) => match.stage_item_id == null || !itemIds.has(match.stage_item_id)
    );
    if (loose.length > 0) sections.push({ key: 0, label: "Unassigned", matches: loose });

    return sections.length > 1 ? sections : null;
  }, [matches, projection.isGroups, stage.items]);

  return (
    <section
      aria-labelledby="bracket-preview-heading"
      className={cn("rounded-lg border border-border bg-card p-4", className)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="bracket-preview-heading" className="text-sm font-semibold text-foreground">
          Bracket preview
        </h3>
        <p className={EYEBROW_CLASS}>
          {generated.length > 0 ? "generated matches" : "read-only projection"}
        </p>
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        <span className="tabular-nums">{projection.itemCount}</span> item
        {projection.itemCount === 1 ? "" : "s"} ·{" "}
        <span className={cn("tabular-nums", unresolved > 0 && TONE_TEXT.warning)}>
          {unresolved}
        </span>{" "}
        unresolved slot{unresolved === 1 ? "" : "s"} ·{" "}
        <span className="tabular-nums">
          {projection.assigned}/{projection.slots}
        </span>{" "}
        seeded
      </p>

      {projection.isBracket ? (
        <p className="mt-3 text-sm text-foreground">
          <span className="font-medium tabular-nums">{bracketTeams.count}</span> team
          {bracketTeams.count === 1 ? "" : "s"}{" "}
          <span className="text-muted-foreground">— {COUNT_SOURCE_NOTE[bracketTeams.source]}</span>
        </p>
      ) : null}

      {projection.isBracket && projection.seeds.lower > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Upstream seeds: <span className="tabular-nums">{projection.seeds.upper}</span> upper ·{" "}
          <span className="tabular-nums">{projection.seeds.lower}</span> lower
        </p>
      ) : null}

      {projection.isGroups ? (
        <p className="mt-3 text-sm text-foreground">
          <span className="font-medium tabular-nums">{projection.itemCount}</span> group
          {projection.itemCount === 1 ? "" : "s"}
          {projection.advancingTotal > 0 ? (
            <span className="text-muted-foreground">
              {" "}
              — top{" "}
              <span className="tabular-nums">
                {[...new Set(projection.advanceCounts)].join(" / ")}
              </span>{" "}
              of each advance, <span className="tabular-nums">{projection.advancingTotal}</span>{" "}
              teams onward
            </span>
          ) : (
            <span className="text-muted-foreground">
              {" "}
              — advancing count auto-derived from the bracket wiring
            </span>
          )}
        </p>
      ) : null}

      <div className="mt-3 border-t border-border pt-3">
        {isLoading ? (
          <Skeleton className="h-64 w-full rounded-2xl" />
        ) : groupSections ? (
          <div className="space-y-4">
            {groupSections.map((section) => (
              <div key={section.key}>
                <p className={cn(EYEBROW_CLASS, "mb-1")}>{section.label}</p>
                <BracketView
                  encounters={section.matches}
                  type={stage.stage_type}
                  interactive={generated.length > 0}
                  onSwapSlots={onSwapSlots}
                />
              </div>
            ))}
          </div>
        ) : matches.length > 0 ? (
          <BracketView
            encounters={matches}
            type={stage.stage_type}
            interactive={generated.length > 0}
            onSwapSlots={onSwapSlots}
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            {isBracket
              ? "Nothing to draw yet — wire at least two teams, or set the preceding group stage's advancing count."
              : "A group stage's matches are drawn once they are generated."}
          </p>
        )}
      </div>
    </section>
  );
}
