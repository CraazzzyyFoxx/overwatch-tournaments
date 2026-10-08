import { getTranslations } from "next-intl/server";

import { KpiList, LeaderboardColumn, LeadersGrid } from "@/components/site/leaders";
import { Column, ColumnHead, Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import statisticsService from "@/services/statistics.service";
import type { TournamentOverall } from "@/types/statistics.types";
import type { Workspace } from "@/types/workspace.types";

const TITLE_ID = "hof-title";
const TOP = 5;

const KPI_KEYS = [
  "tournaments",
  "teams",
  "players",
  "encounters",
  "maps",
  "days",
  "hours",
  "champions"
] as const;

async function Shell({ children }: Readonly<{ children: React.ReactNode }>) {
  const t = await getTranslations("workspace");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        rubric={t("hof.rubric")}
        title={t("hof.title")}
        titleId={TITLE_ID}
        sub={t("hof.sub")}
      />
      {children}
    </Section>
  );
}

function ColumnSkeleton({ rows }: Readonly<{ rows: number }>) {
  return (
    <Column>
      <ColumnHead title={<Skeleton className="h-3 w-32" />} />
      <div>
        {Array.from({ length: rows }, (_, row) => (
          <div
            key={row}
            className="flex min-h-11 items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] last:border-b-0"
          >
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-4 w-10" />
          </div>
        ))}
      </div>
    </Column>
  );
}

export async function HallOfFameSkeleton() {
  return (
    <Shell>
      <LeadersGrid>
        <ColumnSkeleton rows={8} />
        <ColumnSkeleton rows={TOP} />
        <ColumnSkeleton rows={TOP} />
      </LeadersGrid>
    </Shell>
  );
}

/** Everything the community has produced over its whole life: totals and people. */
export async function HallOfFame({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations("workspace");
  const workspaceId = workspace.id;

  const [totals, champions, winrate] = await Promise.all([
    statisticsService.getOverallStatistics({ workspaceId }).catch(() => null),
    statisticsService.getChampions({ workspaceId }).catch(() => null),
    statisticsService.getTopWinratePlayers({ workspaceId }).catch(() => null)
  ]);

  return (
    <Shell>
      <LeadersGrid>
        <KpiList
          title={t("hof.totals")}
          totals={totals as TournamentOverall | null}
          keys={KPI_KEYS}
        />
        <LeaderboardColumn
          title={t("hof.mostWins")}
          sub={t("hof.mostWinsSub")}
          rows={champions === null ? null : champions.results.slice(0, TOP)}
          value="wins"
        />
        <LeaderboardColumn
          title={t("hof.bestWinrate")}
          sub={<span title={t("hof.winrateHint")}>{t("hof.winrateSub")}</span>}
          rows={winrate === null ? null : winrate.results.slice(0, TOP)}
          value="winrate"
          empty={t("hof.winrateEmpty")}
        />
      </LeadersGrid>
    </Shell>
  );
}
