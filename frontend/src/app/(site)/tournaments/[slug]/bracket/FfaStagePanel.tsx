"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import FfaLobbyTable from "@/components/ffa/FfaLobbyTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SegmentedLinks, type SegmentedLinkItem } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type { Stage } from "@/types/tournament.types";

/**
 * An `ffa_league` stage on the public bracket.
 *
 * It replaces `GroupStagePanel` rather than extending it: an FFA stage has no
 * pairings, so there is no bracket to draw and no matches/standings switch to
 * offer — the lobby table IS both. One request answers every lobby of the
 * stage (`GET /tournaments/{id}/stages/{stage_id}/ffa`), so a stage with four
 * groups costs one round trip instead of four.
 */
export function FfaStagePanel({
  tournamentId,
  stage,
  bracketTabs
}: Readonly<{
  tournamentId: number;
  stage: Stage;
  bracketTabs?: readonly SegmentedLinkItem[];
}>) {
  const t = useTranslations();
  const lobbiesQuery = useQuery({
    queryKey: tournamentQueryKeys.ffaStage(tournamentId, stage.id),
    queryFn: () => ffaService.getStage(tournamentId, stage.id)
  });
  const isPreview = !stage.is_published && !stage.is_completed;
  const lobbies = lobbiesQuery.data ?? [];

  return (
    <div className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
      <div className="flex flex-col gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-4">
        {bracketTabs && bracketTabs.length > 1 ? (
          <div className="flex min-w-0 flex-col items-start gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <SegmentedLinks
                items={bracketTabs}
                label={t("tournamentDetail.stageTabsLabel")}
                size="default"
              />
              {isPreview && <Badge variant="outline">{t("common.bracketPreview")}</Badge>}
            </div>
            <p className="text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              {t("ffa.stageLobbies")}
            </p>
          </div>
        ) : (
          <div className="min-w-0">
            <h3 className="truncate text-lg font-semibold text-[color:var(--aqt-fg)]">
              {stage.name}
              {isPreview && (
                <Badge variant="outline" className="ml-2 align-middle">
                  {t("common.bracketPreview")}
                </Badge>
              )}
            </h3>
            <p className="mt-1 text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              {t("ffa.stageLobbies")}
            </p>
          </div>
        )}
      </div>

      <div className="space-y-6 p-4">
        {lobbiesQuery.isPending ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : lobbiesQuery.isError ? (
          <div className="space-y-3 py-8 text-center text-[color:var(--aqt-fg-muted)]">
            <p>{t("ffa.stageFailed")}</p>
            <Button variant="outline" onClick={() => void lobbiesQuery.refetch()}>
              {t("ffa.retry")}
            </Button>
          </div>
        ) : lobbies.length === 0 ? (
          <div className="py-8 text-center text-[color:var(--aqt-fg-muted)]">
            {t("ffa.stageEmpty")}
          </div>
        ) : (
          lobbies.map((lobby) => (
            <section key={lobby.encounter_id} className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <Link
                  href={`/encounters/${lobby.encounter_id}`}
                  className="text-sm font-semibold uppercase tracking-label text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
                >
                  {lobby.name}
                </Link>
                <span className="text-xs uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  {t("ffa.gamesPerLobby")}: {lobby.best_of}
                </span>
              </div>
              {lobby.rows.length === 0 ? (
                <p className="py-4 text-center text-[color:var(--aqt-fg-muted)]">
                  {t("ffa.lobbyEmpty")}
                </p>
              ) : (
                <FfaLobbyTable lobby={lobby} />
              )}
            </section>
          ))
        )}
      </div>
    </div>
  );
}
