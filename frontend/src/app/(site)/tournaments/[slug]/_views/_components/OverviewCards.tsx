"use client";

import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { getStreamStatus, STREAM_STATUS_META } from "@/lib/social/stream-platform";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";

import styles from "../../TournamentDetail.module.css";

/**
 * One block of the overview: a card on the site's first-level surface with a
 * mono eyebrow (wireframes §11) — see `.block` in the module CSS for the
 * treatment and why it is framed.
 */
export function OverviewCard({
  title,
  action,
  id,
  children
}: Readonly<{
  title?: string;
  action?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
}>) {
  return (
    <section className={cn(styles.block, "scroll-mt-28")} id={id}>
      {title || action ? (
        <div className={styles.blockHead}>
          {title ? <h2 className={styles.blockTitle}>{title}</h2> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function CardLink({ href, children }: Readonly<{ href: string; children: React.ReactNode }>) {
  return (
    <HoverPrefetchLink
      href={href}
      className="text-label uppercase tracking-label text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)]"
    >
      {children}
    </HoverPrefetchLink>
  );
}

export function OverviewStreamCard({
  official,
  href,
  action,
  viewers
}: Readonly<{
  official: StreamEntry;
  href: string;
  action: React.ReactNode;
  viewers: string | null;
}>) {
  const t = useTranslations();
  const status = getStreamStatus(official.live);
  const meta = STREAM_STATUS_META[status];

  return (
    <OverviewCard title={t("tournamentDetail.overview.stream.title")} action={action}>
      <HoverPrefetchLink
        href={href}
        className="group relative block overflow-hidden rounded-lg bg-[color:var(--aqt-overlay-2)] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
      >
        {official.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote poster from an arbitrary streaming host; not in `next.config` image domains.
          <img
            src={official.thumbnail_url}
            alt=""
            className="aspect-video w-full object-cover transition-[filter] duration-300 group-hover:brightness-110 motion-reduce:transition-none"
            loading="lazy"
          />
        ) : (
          <span aria-hidden className="block aspect-video w-full bg-[color:var(--aqt-overlay-3)]" />
        )}
        {meta.labelKey && meta.pillStatus ? (
          <TournamentStatusPill status={meta.pillStatus} className="absolute left-3 top-3 z-[1]">
            {t(meta.labelKey)}
          </TournamentStatusPill>
        ) : null}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_42%,hsl(220_22%_4%/0.88))]"
        />
        <span className="absolute inset-x-0 bottom-0 flex flex-col gap-0.5 p-3">
          <span className="text-sm font-semibold text-[color:var(--aqt-fg)]">{official.channel}</span>
          {viewers ? (
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">{viewers}</span>
          ) : null}
        </span>
      </HoverPrefetchLink>
    </OverviewCard>
  );
}

/* `StatTile` and `ROLE_TINT` moved to `_components/RegistrationSummary` so the
   participants page can render the same registration figures. */

export function KeyValue({ term, children }: Readonly<{ term: string; children: React.ReactNode }>) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)] sm:pt-0.5">
        {term}
      </dt>
      <dd className="min-w-0 text-ui text-[color:var(--aqt-fg-muted)]">{children}</dd>
    </div>
  );
}
