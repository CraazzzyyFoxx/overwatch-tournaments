import { Section } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { getPublicCommunities, type PublicCommunity } from "@/lib/site/public-data";
import { deriveWorkspacePalette } from "@/lib/workspace/theme";
import tournamentService from "@/services/tournament.service";
import type { WorkspaceListItem } from "@/types/workspace.types";
import { DomainSteps, type DomainExample } from "./DomainSteps";

/** The example community the mock walks through, when the directory has one. */
const PREFERRED_SLUG = "jaristo-squad";

function isExample(
  community: PublicCommunity
): community is PublicCommunity & { workspace: WorkspaceListItem & { subdomain: string; custom_domain: string } } {
  const { workspace } = community;
  return Boolean(
    workspace.subdomain &&
      workspace.custom_domain &&
      workspace.custom_domain_verified_at &&
      deriveWorkspacePalette(workspace)
  );
}

/**
 * A real community running the whole path: platform page → subdomain and
 * palette → verified custom domain. Its totals come with the directory read
 * the community row already made (`getPublicCommunities` is cached per
 * render). Without one the steps still read — they just lose the addresses
 * and the preview.
 */
async function loadExample(): Promise<DomainExample | null> {
  const directory = await getPublicCommunities().catch(() => [] as PublicCommunity[]);
  const candidates = directory.filter(isExample);
  const example = candidates.find((item) => item.workspace.slug === PREFERRED_SLUG) ?? candidates[0];
  if (!example) return null;
  const { workspace } = example;

  const firstTournaments = await tournamentService
    .listTournaments({ workspaceId: workspace.id, sort: "start_date", order: "asc", perPage: 1 })
    .catch(() => null);

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
    tournaments: example.tournaments,
    players: example.players,
    firstYear
  };
}

export async function DomainsSection() {
  const example = await loadExample();

  return (
    <Section labelledBy="gw-dom-title">
      <DomainSteps example={example} zone={PLATFORM_ZONE} />
    </Section>
  );
}

/** Same boxes as the loaded section: the head and four steps beside one browser frame. */
export function DomainsSkeleton() {
  return (
    <div aria-hidden className="grid items-start gap-x-14 gap-y-8 min-[1024px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
      <div>
        <Skeleton className="h-7 w-[22rem] max-w-full" />
        <Skeleton className="mt-2.5 h-4 w-[26rem] max-w-full" />
        <Skeleton className="mt-8 h-4 w-32" />
        <div className="mt-3 border-l-2 border-[color:var(--aqt-border-2)]">
          {[0, 1, 2, 3].map((step) => (
            <div key={step} className="py-3 pl-4">
              <Skeleton className="h-5 w-56 max-w-full" />
              <Skeleton className="mt-2 h-3.5 w-64 max-w-full" />
              <Skeleton className="mt-2 h-4 w-72 max-w-full" />
            </div>
          ))}
        </div>
      </div>
      <div>
        <Skeleton className="h-[300px] w-full rounded-xl" />
        <Skeleton className="mt-4 h-[150px] w-full rounded-lg" />
      </div>
    </div>
  );
}
