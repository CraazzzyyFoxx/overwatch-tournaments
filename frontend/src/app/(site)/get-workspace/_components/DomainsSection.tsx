import { getTranslations } from "next-intl/server";

import { Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { deriveWorkspacePalette } from "@/lib/workspace/theme";
import statisticsService from "@/services/statistics.service";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import type { Workspace } from "@/types/workspace.types";
import { DomainSteps, type DomainExample } from "./DomainSteps";

/** The example community the mock walks through, when the directory has one. */
const PREFERRED_SLUG = "jaristo-squad";

function isExample(
  workspace: Workspace
): workspace is Workspace & { subdomain: string; custom_domain: string } {
  return Boolean(
    workspace.subdomain &&
      workspace.custom_domain &&
      workspace.custom_domain_verified_at &&
      deriveWorkspacePalette(workspace)
  );
}

/**
 * A real community running the whole path: platform page → subdomain and
 * palette → verified custom domain. Without one the steps still read — they
 * just lose the addresses and the previews.
 */
async function loadExample(): Promise<DomainExample | null> {
  const directory = await workspaceService.getAll("public").catch(() => [] as Workspace[]);
  const candidates = directory.filter(isExample);
  const workspace = candidates.find((item) => item.slug === PREFERRED_SLUG) ?? candidates[0];
  if (!workspace) return null;

  const [totals, firstTournaments] = await Promise.all([
    statisticsService.getOverallStatistics({ workspaceId: workspace.id }).catch(() => null),
    tournamentService
      .listTournaments({ workspaceId: workspace.id, sort: "start_date", order: "asc", perPage: 1 })
      .catch(() => null)
  ]);

  // The year only — read off the ISO date so no timezone is assumed.
  const firstStart = firstTournaments?.results[0]?.start_date;
  const firstYear = firstStart ? String(firstStart).slice(0, 4) : null;

  return {
    workspace: { id: workspace.id, name: workspace.name, icon_url: workspace.icon_url },
    slug: workspace.slug,
    subdomain: workspace.subdomain,
    customDomain: workspace.custom_domain,
    palette: deriveWorkspacePalette(workspace) ?? {},
    swatches: (
      [
        ["brand_primary", workspace.brand_primary],
        ["brand_secondary", workspace.brand_secondary],
        ["brand_background", workspace.brand_background],
        ["brand_surface", workspace.brand_surface]
      ] as const
    ).flatMap(([key, color]) => (color ? [{ key, color }] : [])),
    tournaments: totals?.tournaments ?? null,
    players: totals?.players ?? null,
    firstYear
  };
}

export async function DomainsSection() {
  const t = await getTranslations("getWorkspace.domains");
  const example = await loadExample();

  return (
    <Section labelledBy="gw-dom-title">
      <SectionHead title={t("title")} titleId="gw-dom-title" sub={t("sub")} />
      <DomainSteps example={example} zone={PLATFORM_ZONE} />
    </Section>
  );
}

/** Same boxes as the loaded section: a head, four steps, one preview frame. */
export function DomainsSkeleton() {
  return (
    <div aria-hidden>
      <div className="mb-4">
        <Skeleton className="h-7 w-[22rem] max-w-full" />
        <Skeleton className="mt-2.5 h-4 w-[26rem] max-w-full" />
      </div>
      <div className="grid items-start gap-x-14 min-[1024px]:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div>
          {[0, 1, 2, 3].map((step) => (
            <div key={step} className="border-t border-[color:var(--aqt-border)] pt-[18px] pb-8 min-[1024px]:min-h-[46vh] min-[1024px]:last:min-h-[40vh]">
              <Skeleton className="h-6 w-56 max-w-full" />
              <Skeleton className="mt-2 h-3.5 w-64 max-w-full" />
              <Skeleton className="mt-2 h-4 w-80 max-w-full" />
            </div>
          ))}
        </div>
        <Skeleton className="hidden aspect-[16/10] w-full rounded-xl min-[1024px]:block" />
      </div>
    </div>
  );
}
