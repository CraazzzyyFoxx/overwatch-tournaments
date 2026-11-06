"use client";

import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { MasterDetail } from "@/components/kit/MasterDetail";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useIsMobile } from "@/hooks/useMobile";
import { usePermissions } from "@/hooks/usePermissions";

import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { StageEditor } from "./components/StageEditor";
import { StageList } from "./components/StageList";
import { useBracketTabData } from "./useBracketTabData";

/**
 * Bracket (T4, F7): the stage list on the left, one stage's editor on the right.
 *
 * This replaces `/stages` and its 2450-line `StageManager`, which stacked the
 * list, the editor, a three-level `Advanced` disclosure and seven dialogs onto
 * one screen. The queries, the query keys and every mutation are the same ones;
 * only the shape changed.
 *
 * `?stage=` is written with `mode: "push"` on purpose: below `md` `MasterDetail`
 * shows either the list or the editor, and its "Back to list" button steps the
 * history entry back.
 */
export default function BracketTabPage() {
  const t = useTranslations("adminBracket.page");
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const queryClient = useQueryClient();
  const { isSuperuser } = usePermissions();
  const { searchParams, setParams } = useQueryParams({ mode: "push" });
  const isMobile = useIsMobile();

  const {
    stagesQuery,
    tournamentQuery,
    orderedStages,
    progressByStageId,
    teams,
    isTeamsLoading,
    failedQuery
  } = useBracketTabData(tournamentId);
  const tournament = tournamentQuery.data;

  const stageParam = Number(searchParams?.get("stage"));
  // No `?stage=` on a wide viewport opens the LAST stage — the one still being
  // worked on, since seeding flows top to bottom. Below `md` the list is the
  // landing surface and `MasterDetail`'s Back is `history.back()`, so an
  // implicit selection there would send the reader off the tab.
  const selectedStage =
    orderedStages.find((stage) => stage.id === stageParam) ??
    (isMobile ? null : (orderedStages.at(-1) ?? null));

  if (failedQuery) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError")}
        onAction={() => void failedQuery.refetch()}
      />
    );
  }

  if (stagesQuery.isLoading) {
    return <Skeleton className="h-72 w-full rounded-xl" />;
  }

  return (
    <MasterDetail
      listWidth={300}
      list={
        <StageList
          tournamentId={tournamentId}
          stages={orderedStages}
          progressByStageId={progressByStageId}
          selectedStageId={selectedStage?.id ?? null}
          onSelect={(stageId) => setParams({ stage: stageId, section: null })}
          onChanged={() => void invalidateTournamentWorkspace(queryClient, tournamentId)}
        />
      }
      detail={
        selectedStage ? (
          <StageEditor
            key={selectedStage.id}
            stage={selectedStage}
            stages={orderedStages}
            tournament={tournament}
            teams={teams}
            isTeamsLoading={isTeamsLoading}
            progress={progressByStageId.get(selectedStage.id)}
            isSuperuser={isSuperuser}
            encountersHref={`/admin/tournaments/${tournamentId}/matches/encounters?stage=${selectedStage.id}`}
            onChanged={() => void invalidateTournamentWorkspace(queryClient, tournamentId)}
            onSelect={(stageId) => setParams({ stage: stageId, section: null })}
          />
        ) : null
      }
      emptyDetail={
        <PageStateCard
          state="empty"
          title={orderedStages.length > 0 ? t("noStageSelected") : t("noStages")}
          description={orderedStages.length > 0 ? t("pickStage") : t("addFirstStage")}
        />
      }
    />
  );
}
