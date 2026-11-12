"use client";

import { useCallback, useId, useMemo } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { BracketView, type BracketSlotRef } from "@/components/bracket/BracketView";
import { previewToBracketMatches, type BracketMatch } from "@/lib/bracket/view";
import { seatAt } from "@/lib/encounter/seats";
import { notify } from "@/lib/notify";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BEST_OF_OPTIONS } from "@/lib/tournament/best-of";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { Team } from "@/types/team.types";
import type { Stage } from "@/types/tournament.types";

import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { useHubEncountersQuery } from "../../hubQueries";
import {
  BRACKET_STAGE_TYPES,
  FFA_STAGE_TYPES,
  type StageProjection
} from "@/lib/bracket/projection";
import { adminQueryKeys } from "@/lib/admin/query-keys";

import { useBracketBestOf } from "./useBracketBestOf";

/**
 * The stage as it would be generated right now.
 *
 * The bracket itself is the real tree, drawn by the same `BracketView` the
 * public page uses: once the stage has matches it draws those (scores, live
 * state and all), and before that it draws the skeleton the backend generator
 * would produce (`GET /admin/stages/{id}/bracket-preview`). Neither is a
 * bracket-shaped drawing re-derived here, which is the only way the preview and
 * the generated bracket cannot disagree about byes and lower-bracket drops.
 *
 * The best-of of an elimination bracket is set right here: a default above the
 * tree and a menu on each round header (`useBracketBestOf`). A pick saves at
 * once, so the drawn tree and the cards' "Bo3" follow it.
 *
 * Teams can be rearranged by drag: generated matches swap encounter slots, and
 * a Draft skeleton seeded in slot order swaps the seed inputs behind it.
 * Everything else about a match is the Matches tab's job.
 */
export function BracketPreview({
  projection,
  stage,
  teams,
  onBestOfSaved
}: Readonly<{
  projection: StageProjection;
  stage: Stage;
  teams: Team[];
  /** The stage after a best-of pick saved it; the editor syncs its form from it. */
  onBestOfSaved: (saved: Stage) => void;
}>) {
  const t = useTranslations("adminBracket.preview");
  const tBestOf = useTranslations("adminBracket.bracketBestOf");
  const bestOfId = useId();
  const { bracketTeams, unresolved } = projection;
  const sourceNote = {
    seeded: t("sourceSeeded"),
    slots: t("sourceSlots"),
    unknown: t("sourceUnknown")
  }[bracketTeams.source];

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
    queryKey: adminQueryKeys.stageBracketPreview(stage.id, stage),
    queryFn: () => adminService.getStageBracketPreview(stage.id),
    // A group stage has no bracket to project, so it never asks.
    enabled: isBracket && !encountersQuery.isPending && generated.length === 0,
    // A reseed changes the stage and so the key: keep the old tree on screen
    // while the new one loads instead of flashing the skeleton loader.
    placeholderData: keepPreviousData
  });

  const teamById = useMemo(() => new Map(teams.map((team) => [team.id, team])), [teams]);
  const projected = useMemo(
    () => previewToBracketMatches(previewQuery.data ?? [], teamById),
    [previewQuery.data, teamById]
  );

  const matches: BracketMatch[] = generated.length > 0 ? generated : projected;
  const isLoading = encountersQuery.isPending || (previewQuery.isPending && previewQuery.isFetching);
  const bestOf = useBracketBestOf({ stage, matches, generated, onSaved: onBestOfSaved });

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
        notify.success(t("swapSuccess"));
      } catch (error) {
        notify.apiError(error, { title: t("swapError") });
      }
      invalidateTournamentWorkspace(queryClient, stage.tournament_id);
    },
    [queryClient, stage.tournament_id, t]
  );
  // Before generation the drawn teams ARE the stage's seed inputs, so a drag
  // trades two inputs' teams (the input PATCH swaps with whichever input holds
  // the team it is given). Only in slot order: an SR ranking re-sorts the seeds
  // whatever their slots, so the drop would change nothing.
  const canReseed = isBracket && generated.length === 0 && stage.seed_ranking === "slot";
  const swapSeeds = useCallback(
    async (source: BracketSlotRef, target: BracketSlotRef) => {
      const teamAt = ({ encounter, slot }: BracketSlotRef) =>
        seatAt(encounter.teams, slot)?.team_id ?? null;
      const sourceTeam = teamAt(source);
      const targetTeam = teamAt(target);
      const input = stage.items
        .flatMap((item) => item.inputs)
        .find((row) => row.team_id === sourceTeam);
      // Team ↔ team only: an empty seat is a later round or an unseeded
      // placeholder, not a seed to trade places with.
      if (!input || targetTeam == null || targetTeam === sourceTeam) return;
      try {
        await adminService.updateStageItemInput(input.id, { team_id: targetTeam, input_type: "final" });
        notify.success(t("swapSuccess"));
      } catch (error) {
        notify.apiError(error, { title: t("swapError") });
      }
      invalidateTournamentWorkspace(queryClient, stage.tournament_id);
    },
    [queryClient, stage, t]
  );
  const onSwapSlots = generated.length > 0 ? swapSlots : canReseed ? swapSeeds : undefined;

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
    if (loose.length > 0) sections.push({ key: 0, label: t("unassigned"), matches: loose });

    return sections.length > 1 ? sections : null;
  }, [matches, projection.isGroups, stage.items, t]);

  return (
    // No frame of its own: the bracket below draws its own cards and panels,
    // and a card inside a card inside the editor's card reads as noise.
    <section aria-labelledby="bracket-preview-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="bracket-preview-heading" className="text-sm font-semibold text-foreground">
          {t("title")}
        </h3>
        <p className={eyebrowClass("muted")}>
          {generated.length > 0
            ? t("generated")
            : canReseed
              ? t("projection")
              : t("readonly")}
        </p>
      </div>

      {isBracket && generated.length === 0 && !canReseed ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {t("reseedHint")}
        </p>
      ) : null}

      <p className="mt-1 text-xs text-muted-foreground">
        {t.rich("summary", {
          items: projection.itemCount,
          unresolved,
          assigned: projection.assigned,
          slots: projection.slots,
          num: (chunks) => (
            <span className={cn("tabular-nums", unresolved > 0 && TONE_TEXT.warning)}>{chunks}</span>
          )
        })}
      </p>

      {projection.isBracket ? (
        <p className="mt-3 text-sm text-foreground">
          <span className="text-muted-foreground">{t("teamsSource", { count: bracketTeams.count, source: sourceNote })}</span>
        </p>
      ) : null}

      {isBracket ? (
        <div className="mt-3 flex items-center gap-2">
          <label htmlFor={bestOfId} className="text-xs text-muted-foreground">
            {tBestOf("default")}
          </label>
          <Select
            value={String(stage.best_of.default)}
            onValueChange={(value) => bestOf.setDefault(Number(value))}
            disabled={bestOf.pending}
          >
            <SelectTrigger id={bestOfId} size="sm" className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BEST_OF_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>{`Bo${n}`}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      <div className="mt-3 border-t border-border pt-3">
        {isLoading ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : groupSections ? (
          <div className="space-y-4">
            {groupSections.map((section) => (
              <div key={section.key}>
                <p className={cn(eyebrowClass("muted"), "mb-1")}>{section.label}</p>
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
            renderHeaderAction={isBracket ? bestOf.renderHeaderAction : undefined}
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            {isBracket
              ? t("emptyBracket")
              : FFA_STAGE_TYPES.includes(stage.stage_type)
                ? t("emptyFfa")
                : t("emptyGroup")}
          </p>
        )}
      </div>
      {bestOf.confirmDialog}
    </section>
  );
}
