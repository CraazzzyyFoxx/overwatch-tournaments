import type { ReactNode } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { FEATURED_GLOW } from "@/app/(site)/(home)/_components/NowOnPlatform";
import { NumbersReveal } from "@/app/(site)/(home)/_components/NumbersReveal";
import { Section } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { TrustedBadge } from "@/components/workspace/TrustedBadge";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { getFormatter } from "@/lib/datetime/server";
import { getPublicCommunities } from "@/lib/site/public-data";
import { cn } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";

const TITLE_ID = "gw-proof-title";

/** The row is proof, not the catalogue (the home's carousel is): the biggest communities, two rows of three. */
const SHOWN = 6;

/** Totals on the left, the communities beside them from 1024px behind a rule; stacked below. */
const ROW_CLASS =
  "grid grid-cols-[minmax(0,1fr)] gap-x-10 gap-y-5 border-y border-[color:var(--aqt-border)] py-6 min-[1024px]:grid-cols-[auto_minmax(0,1fr)] min-[1024px]:items-center";

const LIST_CLASS = "min-w-0 min-[1024px]:border-l min-[1024px]:border-[color:var(--aqt-border)] min-[1024px]:pl-10";

const CHIPS_CLASS = "mt-3 grid grid-cols-1 gap-2 min-[480px]:grid-cols-2 min-[900px]:grid-cols-3";

/** The bento's hero figure, a size down: the same face, weight and teal-fading fill. */
const FIGURE_CLASS =
  "block bg-[linear-gradient(180deg,var(--aqt-fg)_30%,var(--aqt-teal)_125%)] bg-clip-text font-display text-[length:clamp(2.75rem,4.6vw,4rem)] font-extrabold leading-none tracking-[-0.04em] text-transparent tabular-nums";

/** A group card per community (DESIGN §5), glowing teal under the pointer like the home's cards. */
const CHIP_CLASS = cn(
  "flex min-h-14 items-center gap-3 rounded-xl border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-1)] py-2 pl-2 pr-3 transition-[border-color,box-shadow,background-color] duration-300 hover:bg-[color:var(--aqt-overlay-2)] focus-visible:outline-none",
  FEATURED_GLOW
);

/** The Directory card's logo glow. */
const LOGO_CLASS =
  "shadow-[0_0_0_1px_var(--aqt-overlay-border),0_12px_36px_-12px_color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]";

const bold = (chunks: ReactNode) => (
  <b className="font-semibold text-[color:var(--aqt-fg-muted)] tabular-nums">{chunks}</b>
);

/**
 * Who already runs tournaments here, right under the hero: the platform's
 * totals counting up once (`NumbersReveal`) beside the biggest public
 * communities, each a link with its logo, trusted badge and own totals. Live
 * data, never a quote. When the directory read fails the row is simply absent:
 * an error box would argue against the page it sits on.
 */
export async function CommunityProof() {
  const [t, kpi, format, communities, totals] = await Promise.all([
    getTranslations("getWorkspace.proof"),
    getTranslations("site.kpi"),
    getFormatter(),
    getPublicCommunities().catch(() => null),
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null)
  ]);
  if (!communities?.length) return null;

  const shown = [...communities]
    .sort((a, b) => (b.tournaments ?? 0) - (a.tournaments ?? 0) || (b.players ?? 0) - (a.players ?? 0))
    .slice(0, SHOWN);

  return (
    <Section labelledBy={TITLE_ID}>
      <div className={ROW_CLASS}>
        {totals ? (
          <NumbersReveal as="dl" className="flex gap-10">
            {(["tournaments", "players"] as const).map((key) => (
              <div key={key}>
                <Eyebrow as="dt">{kpi(key)}</Eyebrow>
                <dd className="mt-2">
                  <b data-count={totals[key]} className={FIGURE_CLASS}>
                    {format.number(totals[key])}
                  </b>
                </dd>
              </div>
            ))}
          </NumbersReveal>
        ) : null}
        <div className={totals ? LIST_CLASS : "min-w-0"}>
          <Eyebrow as="h2" id={TITLE_ID}>
            {t("title")}
          </Eyebrow>
          <ul className={CHIPS_CLASS}>
            {shown.map(({ workspace, tournaments, players }) => (
              <li key={workspace.id} className="min-w-0">
                <Link href={`/workspace/${workspace.slug}`} prefetch={false} className={CHIP_CLASS}>
                  <WorkspaceAvatar workspace={workspace} size={40} className={LOGO_CLASS} />
                  <span className="min-w-0">
                    <span className="flex min-w-0 items-center gap-1.5 font-display text-ui font-semibold leading-snug text-[color:var(--aqt-fg)]">
                      <span className="truncate">{workspace.name}</span>
                      <TrustedBadge status={workspace.verification_status} />
                    </span>
                    {tournaments !== null && players !== null ? (
                      <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
                        {t.rich("counts", {
                          tournaments: format.number(tournaments),
                          tournamentsCount: tournaments,
                          players: format.number(players),
                          playersCount: players,
                          b: bold
                        })}
                      </span>
                    ) : null}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}

/** The same row while the reads are out: two figures, a label, two rows of three cards. */
export function CommunityProofSkeleton() {
  return (
    <div aria-hidden className={ROW_CLASS}>
      <div className="flex gap-10">
        {[0, 1].map((index) => (
          <div key={index}>
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-14 w-28" />
          </div>
        ))}
      </div>
      <div className={LIST_CLASS}>
        <Skeleton className="h-3 w-48" />
        <div className={CHIPS_CLASS}>
          {Array.from({ length: SHOWN }).map((_, index) => (
            <Skeleton key={index} className="h-14 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}
