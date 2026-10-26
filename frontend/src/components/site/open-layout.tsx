import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, CircleAlert, Info } from "lucide-react";

import { Eyebrow } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";
import { RetryButton } from "./RetryButton";

/**
 * The "open layout" of the platform pages (home, community page, organizer
 * page): sections on hairline rules instead of boxes. Line hierarchy — section
 * rule (fg-faint) > column/item rules (border-3) > rows (border).
 *
 * Presentational and hook-light (`useTranslations` only), so every export here
 * renders from a Server Component as well as from a client one.
 */

/** Lead paragraph under a hero title (mock `.lede`). */
export const LEDE_CLASS =
  "max-w-[40rem] text-pretty text-ui leading-[1.6] text-[color:var(--aqt-fg-muted)]";

/** Section h2 / standalone large title (mock `.sec .h-title`). */
export const SECTION_TITLE_CLASS =
  "text-balance font-display text-[length:clamp(24px,2.2vw,30px)] font-bold leading-[1.15] tracking-[-0.01em] text-[color:var(--aqt-fg)]";

/**
 * Hero h1 size of the redesigned platform pages (mock `--text-display`). Kept
 * local instead of changing the global `text-display` role, which every other
 * page hero still uses at its larger size.
 */
export const HERO_TITLE_SIZE_CLASS = "text-[length:clamp(2rem,3.4vw,2.75rem)]";

/** A page's stack of sections, one `--section-gap` apart (mock `.home`, `.ws-main`, `.gw`). */
export function SectionStack({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <div className={cn("flex flex-col gap-[var(--section-gap)]", className)}>{children}</div>;
}

/**
 * One section of the page. `closed` draws the rule under the page's "now"
 * block — the only section that closes with one.
 */
export function Section({
  labelledBy,
  closed = false,
  id,
  className,
  children
}: Readonly<{ labelledBy: string; closed?: boolean; id?: string; className?: string; children: ReactNode }>) {
  return (
    <section
      id={id}
      aria-labelledby={labelledBy}
      className={cn(
        "scroll-mt-[var(--aqt-sticky-top)]",
        closed && "border-b border-[color:var(--aqt-fg-faint)] pb-10",
        className
      )}
    >
      {children}
    </section>
  );
}

/** "View all →" — the exit of a digest block (mock `.more`). */
export function MoreLink({
  href,
  children,
  className,
  ...rest
}: Readonly<{ href: string; children: ReactNode; className?: string; "aria-hidden"?: boolean; tabIndex?: number }>) {
  return (
    <Link
      href={href}
      prefetch={false}
      className={cn(
        "group/more inline-flex min-h-8 items-center gap-1.5 rounded-md font-[family-name:var(--aqt-data)] text-label font-semibold uppercase tracking-label",
        "text-[color:var(--aqt-teal)] hover:text-[color:color-mix(in_srgb,var(--aqt-teal)_78%,white)]",
        className
      )}
      {...rest}
    >
      {children}
      <ArrowRight
        className="size-3.5 transition-transform duration-150 group-hover/more:translate-x-0.5"
        aria-hidden
      />
    </Link>
  );
}

/**
 * Section head: a rubric over a large title, an optional dim line under it,
 * and the section's exit (a "more" link) or controls on the right.
 */
export function SectionHead({
  rubric,
  title,
  titleId,
  sub,
  aside
}: Readonly<{ rubric?: ReactNode; title: ReactNode; titleId: string; sub?: ReactNode; aside?: ReactNode }>) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
      <div>
        {rubric ? <Eyebrow className="mb-1.5 block">{rubric}</Eyebrow> : null}
        <h2 id={titleId} className={SECTION_TITLE_CLASS}>
          {title}
        </h2>
        {sub ? <p className="mt-1.5 text-body text-[color:var(--aqt-fg-dim)]">{sub}</p> : null}
      </div>
      {aside}
    </div>
  );
}

/** Open column: an uppercase head between two rules, rows flush under it (mock `.col`). */
export function Column({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <div className={cn("min-w-0", className)}>{children}</div>;
}

export function ColumnHead({ title, sub }: Readonly<{ title: ReactNode; sub?: ReactNode }>) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 border-y border-t-[color:var(--aqt-border-3)] border-b-[color:var(--aqt-border)]">
      <Eyebrow as="h3" tone="muted">
        {title}
      </Eyebrow>
      {sub ? <span className="whitespace-nowrap text-caption text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
    </div>
  );
}

/** A figure over its uppercase label (mock `.metric`). */
export function Fact({ value, label }: Readonly<{ value: ReactNode; label: ReactNode }>) {
  return (
    <span className="[&+&]:border-l [&+&]:border-[color:var(--aqt-border)] [&+&]:pl-[22px]">
      <b className="block font-[family-name:var(--aqt-data)] text-ui font-bold leading-[1.2] tabular-nums text-[color:var(--aqt-fg)]">
        {value}
      </b>
      <Eyebrow>{label}</Eyebrow>
    </span>
  );
}

export function Facts({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <div className={cn("flex flex-wrap gap-x-[22px] gap-y-3", className)}>{children}</div>;
}

export type FeatTone = "live" | "upcoming" | "past";

const FEAT_TONE: Record<FeatTone, string> = {
  live: "var(--aqt-status-live)",
  upcoming: "var(--aqt-status-upcoming)",
  past: "var(--aqt-fg-faint)"
};

/**
 * The page's lead tournament: no box, a 2px rule in its status colour, the
 * kicker in the same colour (mock `.feat`). `head` is the name block that
 * sits under the kicker; `children` (facts, actions, a "more" link) are its
 * siblings, so a tall card spreads them top to bottom.
 */
export function Feat({
  tone,
  kicker,
  head,
  children,
  className
}: Readonly<{
  tone: FeatTone;
  kicker: ReactNode;
  head: ReactNode;
  children?: ReactNode;
  className?: string;
}>) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col items-start justify-between gap-[22px] border-t-2 border-[color:var(--feat-c)] pt-5",
        className
      )}
      style={{ "--feat-c": FEAT_TONE[tone] } as CSSProperties}
    >
      <div className="min-w-0 self-stretch">
        <Eyebrow as="div" className="mb-3.5 flex items-center gap-[9px] text-[color:var(--feat-c)] [&_svg]:size-3.5">
          {kicker}
        </Eyebrow>
        {head}
      </div>
      {children}
    </div>
  );
}

/** The lead tournament's name (mock `.feat__name`). */
export const FEAT_NAME_CLASS =
  "text-balance font-display text-[length:clamp(22px,2vw,28px)] font-bold leading-[1.15] text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-fg-muted)]";

/** Dim meta line under the lead name (mock `.feat__meta`); its icon is gold. */
export const FEAT_META_CLASS =
  "mt-1.5 text-caption text-[color:var(--aqt-fg-dim)] [&_svg]:inline [&_svg]:size-3.5 [&_svg]:-translate-y-px [&_svg]:text-[color:var(--aqt-gold)]";

/** The winning roster as a wrapped row of player links (mock `.roster`). */
export function Roster({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-2.5 gap-y-1 text-caption text-[color:var(--aqt-fg-dim)] [&_a:hover]:text-[color:var(--aqt-fg)]">
      {children}
    </div>
  );
}

/** The live pulse dot (mock `.live-dot`), in `currentColor`. */
export function LiveDot({ className }: Readonly<{ className?: string }>) {
  return (
    <span aria-hidden className={cn("relative inline-flex size-[7px] shrink-0 rounded-full bg-current shadow-[0_0_0_3px_color-mix(in_srgb,currentColor_18%,transparent)]", className)}>
      <span className="absolute inset-0 rounded-full bg-current motion-safe:animate-ping" />
    </span>
  );
}

/** The open layout's state row (mock `.state`): an icon beside a bold line and its reason. */
function StateRow({
  icon,
  title,
  dashed = false,
  role,
  children
}: Readonly<{ icon: ReactNode; title: ReactNode; dashed?: boolean; role?: "status"; children?: ReactNode }>) {
  return (
    <div
      role={role}
      className={cn(
        "flex items-start gap-3 py-[18px] text-body text-[color:var(--aqt-fg-muted)]",
        dashed && "rounded-xl border border-dashed border-[color:var(--aqt-border-2)] px-[18px]"
      )}
    >
      {icon}
      <div>
        <b className="mb-0.5 block font-semibold text-[color:var(--aqt-fg)]">{title}</b>
        {children}
      </div>
    </div>
  );
}

/**
 * A block that failed to load. `dashed` frames a whole section's body; the
 * default is the inline variant inside a column. Says it is an error and not
 * an empty list, and offers a retry.
 */
export function OpenLoadError({ what, dashed = false }: Readonly<{ what?: string; dashed?: boolean }>) {
  const t = useTranslations("site.state");
  return (
    <StateRow
      role="status"
      dashed={dashed}
      icon={<CircleAlert className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-rose)]" aria-hidden />}
      title={what ? t("loadFailedWhat", { what }) : t("loadFailed")}
    >
      {dashed ? (
        <>
          {t("notEmpty")}
          <br />
        </>
      ) : null}
      <RetryButton />
    </StateRow>
  );
}

/** "Nothing yet" inside a column, with the reason (mock `.state` + info icon). */
export function OpenEmptyRow({ children }: Readonly<{ children?: ReactNode }>) {
  const t = useTranslations("site.state");
  return (
    <StateRow
      icon={<Info className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-fg-faint)]" aria-hidden />}
      title={t("empty")}
    >
      {children}
    </StateRow>
  );
}
