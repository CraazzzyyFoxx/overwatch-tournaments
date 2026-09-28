"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
        <div className="flex items-center gap-1">
          {PREVIEW_LENGTHS.map((length) => (
            <Button
              key={length}
              type="button"
              size="sm"
              variant={length === previewBestOf ? "default" : "ghost"}
              aria-pressed={length === previewBestOf}
              onClick={() => setSelected(length)}
            >
              {t("preview.bestOf", { bestOf: length })}
            </Button>
          ))}
        </div>
      </div>

      {preview.isPending ? <Skeleton className="h-24 w-full rounded-lg" /> : null}

      {preview.isError ? (
        <p className="text-xs text-muted-foreground">{t("preview.failed")}</p>
      ) : null}

      {preview.data ? (
        <>
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {preview.data.maps.map((map) => (
              <li key={map.map_index} className="rounded-md border border-border bg-card p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    {t("preview.map", { n: map.map_index })}
                  </span>
                  <Badge variant="secondary">
                    {map.phase_id ?? t("preview.noPhase")}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("preview.bans", {
                    added: map.max_new_bans,
                    active: map.max_active_bans,
                    steps: map.steps.length,
                  })}
                </p>
                {map.worst_case_remaining ? (
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {Object.entries(map.worst_case_remaining).map(([group, left]) => (
                      <li key={group}>
                        <Badge variant={left < 2 ? "destructive" : "outline"}>
                          {t("preview.remaining", { group, count: left })}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
          <IssueList issues={preview.data.issues} />
        </>
      ) : null}
    </div>
  );
}
