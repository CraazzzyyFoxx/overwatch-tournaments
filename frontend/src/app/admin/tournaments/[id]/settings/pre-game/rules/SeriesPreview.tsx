"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import pickBanService from "@/services/pickBan.service";
import type { MapVetoMode, PickBanKind, PickBanRuleset } from "@/types/tournament.types";

import { IssueList } from "./IssueList";

/** The series lengths a bracket actually plays. Bo4/Bo6 are legal but unused. */
const PREVIEW_LENGTHS = [1, 2, 3, 5] as const;

/**
 * What the ruleset does to a whole series, map by map (§10).
 *
 * The constructor's most important answer: an organizer authoring "five bans
 * each, alive for two maps" cannot work out in their head how many heroes are
 * left on map 4. The engine computes it — same code path the room runs — and
 * the worst case per role is what says whether the rules are playable at all.
 */
export function SeriesPreview({
  tournamentId,
  kind,
  mode,
  ruleset,
  itemIds,
  slots,
  bestOf,
}: Readonly<{
  tournamentId: number;
  kind: PickBanKind;
  mode: MapVetoMode;
  ruleset: PickBanRuleset;
  itemIds: number[];
  slots: { candidates: number[]; reserve_item_id?: number | null }[];
  /** The scope's own series length, the preview's default selection. */
  bestOf: number;
}>) {
  const t = useTranslations("pickBan.rules");
  const [selected, setSelected] = useState<number | null>(null);
  const previewBestOf = selected ?? bestOf;

  const preview = useQuery({
    queryKey: tournamentQueryKeys.pickBanRulesPreview(
      tournamentId,
      kind,
      mode,
      previewBestOf,
      ruleset,
      { itemIds, slots }
    ),
    queryFn: () =>
      pickBanService.previewRuleset(tournamentId, {
        kind,
        mode,
        ruleset,
        best_of: previewBestOf,
        item_ids: itemIds,
        slots,
      }),
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">{t("preview.title")}</p>
        <ToggleGroup
          variant="pill"
          size="sm"
          value={String(previewBestOf)}
          onValueChange={(next) => {
            if (next) setSelected(Number(next));
          }}
          aria-label={t("preview.title")}
        >
          {PREVIEW_LENGTHS.map((length) => (
            <ToggleGroupItem key={length} value={String(length)}>
              {t("preview.bestOf", { bestOf: length })}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {preview.isPending ? <Skeleton className="h-24 w-full rounded-lg" /> : null}

      {preview.isError ? (
        <p className="text-xs text-muted-foreground">{t("preview.failed")}</p>
      ) : null}

      {preview.data ? (
        <>
          <ul className="flex flex-col divide-y divide-border">
            {preview.data.maps.map((map) => {
              const phaseIndex = ruleset.phases.findIndex((phase) => phase.id === map.phase_id);
              const phase = ruleset.phases[phaseIndex];
              const remaining = Object.entries(map.worst_case_remaining ?? {});
              return (
                <li key={map.map_index} className="py-2">
                  <p className="text-sm">
                    <span className="font-medium">{t("preview.map", { n: map.map_index })}</span>
                    {phase ? (
                      <span className="text-muted-foreground">
                        {" · "}
                        {phase.name ?? t("preview.phase", { n: phaseIndex + 1 })}
                      </span>
                    ) : null}
                  </p>
                  {map.phase_id == null ? (
                    <p className="text-xs text-danger">{t("preview.noPhase")}</p>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    {t("preview.bans", {
                      added: map.max_new_bans,
                      active: map.max_active_bans,
                      steps: map.steps.length,
                    })}
                  </p>
                  {remaining.length > 0 ? (
                    <p className="text-xs text-muted-foreground">
                      {remaining.map(([group, left], index) => (
                        <span key={group}>
                          {index > 0 ? " · " : null}
                          <span className={cn(left < 2 && "text-danger")}>
                            {t("preview.remaining", { group, count: left })}
                          </span>
                        </span>
                      ))}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <IssueList issues={preview.data.issues} />
        </>
      ) : null}
    </div>
  );
}
