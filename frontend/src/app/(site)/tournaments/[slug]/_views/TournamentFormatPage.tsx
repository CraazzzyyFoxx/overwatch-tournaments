"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { portsFromRead, toCanvas } from "@/lib/flow/flowCanvas";
import { draftFromRead, keyedValidation } from "@/lib/flow/flowDraft";
import type { Tournament } from "@/types/tournament.types";

import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentBracketSkeleton } from "../_components/TournamentSkeletons";
import { flowQueryOptions } from "../_queries/flow";

const TournamentFormatView = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const flowQuery = useQuery(flowQueryOptions(tournament));
  const canvas = useMemo(() => {
    if (!flowQuery.data) return null;
    const draft = draftFromRead(flowQuery.data);
    const keyed = keyedValidation(draft, [], portsFromRead(flowQuery.data));
    return toCanvas(draft, keyed.ports, new Map(), new Set(), true);
  }, [flowQuery.data]);

  if (!canvas) {
    return flowQuery.isError ? (
      <TournamentPageState state="initial-error" onRetry={() => void flowQuery.refetch()} />
    ) : (
      <TournamentBracketSkeleton />
    );
  }

  return (
    <div className="space-y-3" data-page-section="format">
      <h2 className="sr-only">{t("common.format")}</h2>
      <FlowCanvas nodes={canvas.nodes} edges={canvas.edges} readOnly heightClass="h-[70vh]" />
      <p className="text-caption text-muted-foreground">{t("tournamentDetail.format.hint")}</p>
    </div>
  );
};

/** Resolves the shared tournament overview, like every other tab view. */
const TournamentFormatPage = ({ slug }: { slug: string }) => {
  const tournamentQuery = useTournamentQuery(slug);

  if (!tournamentQuery.data) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentBracketSkeleton />;
  }

  return <TournamentFormatView tournament={tournamentQuery.data} />;
};

export default TournamentFormatPage;
