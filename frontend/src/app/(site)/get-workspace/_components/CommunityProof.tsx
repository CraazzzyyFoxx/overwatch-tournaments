import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { KpiFigure } from "@/components/site/leaders";
import { Section } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { getFormatter } from "@/lib/datetime/server";
import { getPublicWorkspaces } from "@/lib/site/public-data";
import statisticsService from "@/services/statistics.service";

const TITLE_ID = "gw-proof-title";

/** Totals on the left, the communities beside them from 900px; stacked below. */
const ROW_CLASS =
  "grid gap-x-12 gap-y-6 border-y border-[color:var(--aqt-border)] py-6 min-[900px]:grid-cols-[auto_minmax(0,1fr)] min-[900px]:items-center";

const TOTALS_CLASS = "grid gap-x-10 gap-y-3 sm:grid-cols-2";

/**
 * Who already runs tournaments here, right under the hero: the verified
 * communities of the public directory and the platform's totals. Live data,
 * never a quote. When the directory read fails the row is simply absent: an
 * error box would argue against the page it sits on.
 */
export async function CommunityProof() {
  const [t, kpi, format, workspaces, totals] = await Promise.all([
    getTranslations("getWorkspace.proof"),
    getTranslations("site.kpi"),
    getFormatter(),
    getPublicWorkspaces().catch(() => null),
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null)
  ]);
  if (!workspaces?.length) return null;

  return (
    <Section labelledBy={TITLE_ID}>
      <div className={ROW_CLASS}>
        {totals ? (
          <dl className={TOTALS_CLASS}>
            <KpiFigure label={kpi("tournaments")} value={format.number(totals.tournaments)} />
            <KpiFigure label={kpi("players")} value={format.number(totals.players)} />
          </dl>
        ) : null}
        <div className="min-w-0">
          <Eyebrow as="h2" id={TITLE_ID}>
            {t("title")}
          </Eyebrow>
          <ul className="mt-2 flex flex-wrap gap-x-6">
            {workspaces.map((workspace) => (
              <li key={workspace.id} className="min-w-0">
                <Link
                  href={`/workspace/${workspace.slug}`}
                  prefetch={false}
                  className="flex min-h-11 items-center gap-2.5 text-body font-medium text-[color:var(--aqt-fg-muted)] transition-colors duration-150 hover:text-[color:var(--aqt-fg)]"
                >
                  <WorkspaceAvatar workspace={workspace} size={28} />
                  <span className="truncate">{workspace.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}

/** The same row while the reads are out: two figures, a label, a line of marks. */
export function CommunityProofSkeleton() {
  return (
    <div aria-hidden className={ROW_CLASS}>
      <div className={TOTALS_CLASS}>
        <Skeleton className="h-12 w-28" />
        <Skeleton className="h-12 w-28" />
      </div>
      <div>
        <Skeleton className="h-3 w-48" />
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-2 py-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-7 w-28" />
          ))}
        </div>
      </div>
    </div>
  );
}
