"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SelectContent, SelectGroup, SelectItem } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipSelect } from "@/components/ui/tooltip-select";
import type { SlotProps } from "@/disciplines/types";
import { analyticsQueryKeys } from "@/lib/analytics/query-keys";
import analyticsService from "@/services/analytics.service";

import { type GlossaryTerm } from "./analytics-glossary";
import { getPreferredAnalyticsAlgorithmId, sortAnalyticsAlgorithms } from "./analytics.helpers";
import KpiStats, { KpiStatsSkeleton } from "./components/KpiStats";
import MasterDetail from "./components/MasterDetail";
import OrganizerTools from "./components/OrganizerTools";
import { type StandingsMode } from "./components/StandingsList";
import VerdictLede from "./components/VerdictLede";
import { useAnalyticsViewModel } from "./useAnalyticsViewModel";

function parseId(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** The board's first paint: its toolbar row, then the standings list beside the team panel. */
function AnalyticsBoardSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <Skeleton className="h-8 w-72 max-w-full rounded-lg" />
        <Skeleton className="h-8 w-28 rounded-lg" />
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(21rem,1fr)]">
        <Card className="space-y-px overflow-hidden">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-[3.75rem] rounded-none" />
          ))}
        </Card>
        <Skeleton className="hidden h-[26rem] rounded-xl lg:block" />
      </div>
    </div>
  );
}

type SheetState = { kind: "term"; term: GlossaryTerm } | { kind: "how" };

function TermBody({ term }: Readonly<{ term: GlossaryTerm }>) {
  const t = useTranslations();
  return (
    <SheetHeader>
      <Eyebrow>{t("analytics.sheet.glossaryKicker")}</Eyebrow>
      <SheetTitle>{t(`analytics.glossary.${term}.label`)}</SheetTitle>
      <SheetDescription>{t(`analytics.glossary.${term}.plain`)}</SheetDescription>
    </SheetHeader>
  );
}

function HowBody() {
  const t = useTranslations();
  const steps = [1, 2, 3] as const;
  return (
    <>
      <SheetHeader>
        <Eyebrow>{t("analytics.howItWorks.kicker")}</Eyebrow>
        <SheetTitle>{t("analytics.howItWorks.title")}</SheetTitle>
        <SheetDescription>{t("analytics.howItWorks.intro")}</SheetDescription>
      </SheetHeader>
      <ol className="mt-4 flex flex-col gap-4">
        {steps.map((step) => (
          <li className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-2" key={step}>
            <span className="aqt-tnum pt-px text-label text-[color:var(--aqt-fg-faint)]">{`0${step}`}</span>
            <span>
              <span className="block text-ui font-semibold text-[color:var(--aqt-fg)]">
                {t(`analytics.howItWorks.step${step}Title`)}
              </span>
              <span className="mt-0.5 block text-body text-[color:var(--aqt-fg-muted)]">
                {t(`analytics.howItWorks.step${step}Body`)}
              </span>
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-caption text-[color:var(--aqt-fg-dim)]">{t("analytics.howItWorks.foot")}</p>
    </>
  );
}

/**
 * Overwatch's tournament analytics board (the `analytics` slot): the ranking-algorithm choice (`?algorithm=`), the
 * v1 shift result plus the permission-gated v2 ML reads, and what the page shows from them — the verdict and the six
 * figures in the host's hero, the standings beside the team/player panel below it. Every read is keyed by this
 * tournament (and owner workspace), with no placeholder: another tournament's algorithms or result never stand in
 * while this one's load, and the result is not requested until this tournament's own algorithm list has confirmed
 * the chosen id.
 */
export default function AnalyticsBoard({
  tournamentId,
  workspaceId,
  metadata,
  canReadV2,
  canUpdate,
  ended,
  hero
}: Readonly<SlotProps["analytics"]>) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const t = useTranslations();

  const algorithmId = parseId(searchParams.get("algorithm"));

  const algorithmsQuery = useQuery({
    // Per tournament: each list carries that tournament's `has_data`, which picks the default.
    queryKey: analyticsQueryKeys.algorithms(tournamentId),
    queryFn: ({ signal }) => analyticsService.getAlgorithms(tournamentId, { signal })
  });
  const algorithms = useMemo(
    () => sortAnalyticsAlgorithms(algorithmsQuery.data?.results ?? []),
    [algorithmsQuery.data?.results]
  );
  const activeAlgorithm = algorithms.find((algorithm) => algorithm.id === algorithmId) ?? null;
  const preferredAlgorithmId = getPreferredAnalyticsAlgorithmId(algorithms);

  const analyticsQuery = useQuery({
    queryKey: analyticsQueryKeys.performance(workspaceId, tournamentId, algorithmId),
    queryFn: ({ signal }) => analyticsService.getAnalytics(tournamentId, algorithmId!, workspaceId, { signal }),
    enabled: activeAlgorithm !== null
  });
  const analytics = analyticsQuery.data;

  const { data: performanceRows } = useQuery({
    queryKey: analyticsQueryKeys.performanceV2(tournamentId),
    queryFn: ({ signal }) => analyticsService.getPerformanceV2(tournamentId, undefined, { signal }),
    enabled: canReadV2
  });
  const performanceByPlayer = useMemo(
    () => new Map((performanceRows ?? []).map((row) => [row.player_id, row])),
    [performanceRows]
  );

  // Monte Carlo standings distribution — woven into the team detail (and the
  // organizer table view); gated to analytics.read viewers.
  const { data: standingsRows } = useQuery({
    queryKey: analyticsQueryKeys.standingsDistribution(tournamentId),
    queryFn: ({ signal }) => analyticsService.getStandingsDistribution(tournamentId, undefined, { signal }),
    enabled: canReadV2,
    staleTime: 60_000
  });
  const distributionByTeam = useMemo(
    () => new Map((standingsRows ?? []).map((row) => [row.team_id, row])),
    [standingsRows]
  );

  // Fan-facing view model: per-player impact, the six KPIs, the verdict. Derived from the public v1 payload (+ v2
  // impact when allowed).
  const viewModel = useAnalyticsViewModel(analytics, performanceByPlayer, canReadV2);

  // Glossary / how-it-works explainer sheet, opened by the info dots and the hero's guide action.
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const explain = useCallback((term: GlossaryTerm) => setSheet({ kind: "term", term }), []);

  const [standingsMode, setStandingsMode] = useState<StandingsMode>("standings");

  // An absent or unknown ranking (e.g. one kept in the URL from another tournament) is replaced, without a history
  // entry, by this tournament's preferred one once its list has loaded.
  const replaceAlgorithm = algorithmsQuery.isSuccess && preferredAlgorithmId !== null && activeAlgorithm === null;
  useEffect(() => {
    if (!replaceAlgorithm) return;
    const next = new URLSearchParams(searchParams.toString());
    next.set("algorithm", String(preferredAlgorithmId));
    router.replace(`${pathname}?${next.toString()}`);
  }, [replaceAlgorithm, preferredAlgorithmId, pathname, router, searchParams]);

  const pushAlgorithm = (value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set("algorithm", value);
    router.push(`${pathname}?${next.toString()}`);
  };

  const algorithmPicker = algorithmsQuery.isPending ? (
    <div role="status" className="min-w-[9rem] flex-[0_1_12rem]">
      <span className="sr-only">{t("analytics.briefing.loadingAlgorithms")}</span>
      <Skeleton aria-hidden className="h-8 w-full" />
    </div>
  ) : (
    <TooltipSelect
      tooltip={t("analytics.briefing.algorithm")}
      value={activeAlgorithm ? String(activeAlgorithm.id) : ""}
      placeholder={
        algorithmsQuery.isError ? t("analytics.briefing.errorAlgorithms") : t("analytics.briefing.selectAlgorithm")
      }
      disabled={algorithmsQuery.isError}
      size="sm"
      className="min-w-[9rem] flex-[0_1_12rem]"
      onValueChange={pushAlgorithm}
    >
      <SelectContent>
        <SelectGroup>
          {algorithms.map((item) => (
            <SelectItem key={item.id} value={item.id.toString()}>
              {item.name}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </TooltipSelect>
  );

  // One body per state, in priority order: a failed read outranks a pending one so a retry is offered instead of a
  // skeleton that will never resolve.
  const renderBody = () => {
    if (algorithmsQuery.isError) {
      return (
        <PageStateCard
          state="error"
          title={t("analytics.page.unavailable")}
          description={t("analytics.page.unavailableDesc")}
          onAction={() => void algorithmsQuery.refetch()}
        />
      );
    }
    if (algorithmsQuery.isPending || replaceAlgorithm) return <AnalyticsBoardSkeleton />;
    if (activeAlgorithm === null) {
      return (
        <PageStateCard
          state="empty"
          title={t("analytics.page.chooseParams")}
          description={t("analytics.page.chooseParamsDesc")}
        />
      );
    }
    if (analyticsQuery.isError) {
      return (
        <PageStateCard
          state="error"
          title={t("analytics.page.unavailable")}
          description={t("analytics.page.unavailableDesc")}
          onAction={() => void analyticsQuery.refetch()}
        />
      );
    }
    if (!analytics || !viewModel) return <AnalyticsBoardSkeleton />;
    if (analytics.teams.length === 0) {
      return (
        <PageStateCard
          state="empty"
          title={t("analytics.page.noTeams")}
          description={t("analytics.page.noTeamsDesc")}
        />
      );
    }
    return (
      <MasterDetail
        key={`${tournamentId}-${algorithmId}`}
        tournamentId={tournamentId}
        teams={viewModel.teams}
        canReadV2={canReadV2}
        ended={ended}
        showGroups={viewModel.groupCount > 1}
        mode={standingsMode}
        onModeChange={setStandingsMode}
        performanceByPlayer={performanceByPlayer}
        distributionByTeam={distributionByTeam}
        ontology={metadata}
        onExplain={explain}
      />
    );
  };

  // The figures keep their footprint while this ranking's result loads, so the hero does not grow when they land.
  const loadingResult = activeAlgorithm !== null && !analyticsQuery.isError && !viewModel;

  return (
    <>
      {hero({
        counts:
          analytics && viewModel
            ? { teams: analytics.summary.total_teams, players: analytics.summary.total_players }
            : null,
        lede: viewModel ? <VerdictLede verdict={viewModel.verdict} onExplain={explain} /> : undefined,
        stats: viewModel ? (
          <KpiStats kpis={viewModel.kpis} onExplain={explain} />
        ) : loadingResult ? (
          <KpiStatsSkeleton />
        ) : undefined,
        actions: (
          <Button type="button" variant="outline" size="sm" onClick={() => setSheet({ kind: "how" })}>
            <CircleHelp aria-hidden />
            {t("analytics.sheet.help")}
          </Button>
        ),
        controls: algorithmPicker
      })}
      {canUpdate ? <OrganizerTools tournamentId={tournamentId} workspaceId={workspaceId} /> : null}
      {renderBody()}
      {/* Glossary / how-it-works explainer, a bottom drawer; it only mounts while open (Radix portal). */}
      <Sheet
        open={sheet != null}
        onOpenChange={(open) => {
          if (!open) setSheet(null);
        }}
      >
        <SheetContent side="bottom" className="mx-auto max-h-[85vh] max-w-lg overflow-y-auto">
          {sheet?.kind === "term" ? <TermBody term={sheet.term} /> : null}
          {sheet?.kind === "how" ? <HowBody /> : null}
        </SheetContent>
      </Sheet>
    </>
  );
}
