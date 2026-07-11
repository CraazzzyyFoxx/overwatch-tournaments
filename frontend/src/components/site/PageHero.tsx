import React from "react";

import { cn } from "@/lib/utils";

/**
 * Editorial-Tactical page hero (design-book / OWT artifact).
 *
 * The single restrained hero used across every `(site)` page. Replaces the
 * previous per-page multicolored banners (teal + rose/amber/blue glows + hex
 * lattice) with one calm treatment: a 2px teal top hairline, a faint masked
 * square grid, ONE low-opacity teal glow, and a mixed-case Onest title whose
 * accent word (wrapped in `<em>`) is painted with the role-spectrum gradient.
 *
 * Server-safe: presentational only, no hooks — usable from RSC and client
 * components alike. Colours come from the global `--aqt-*` tokens.
 */

/** Role hue for the profile wash — maps to the `--aqt-{role}` role tokens. */
export type HeroRoleTint = "tank" | "damage" | "support";

interface HeroFrameProps {
  children: React.ReactNode;
  className?: string;
  /**
   * Accent treatment. `"default"` (used by every list/dashboard hero) keeps the
   * calm teal top hairline. `"profile"` is the player-page signature from the
   * design-book: the role-spectrum hairline moves to the BASE and a role-tinted
   * wash bleeds from the top-left — the one place the multi-hue spectrum reads
   * as identity rather than decoration.
   */
  variant?: "default" | "profile";
  /** Role hue for the `"profile"` wash. Omit to skip the tint. */
  roleTint?: HeroRoleTint;
}

/** The decorative shell only — for heroes with bespoke inner content. */
export function HeroFrame({
  children,
  className,
  variant = "default",
  roleTint,
}: HeroFrameProps) {
  const isProfile = variant === "profile";
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]",
        className
      )}
    >
      {/* Accent hairline: teal at the top by default; role-spectrum at the base
          for the player profile (its signature treatment). `overflow-hidden`
          on the section clips the bar cleanly inside the rounded corners. */}
      {isProfile ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 z-[2] h-0.5 opacity-90"
          style={{ background: "var(--aqt-spectrum)" }}
        />
      ) : (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 z-[2] h-0.5 bg-[color:var(--aqt-teal)]"
        />
      )}
      {/* faint square grid, radially masked so it fades out */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-45"
        style={{
          backgroundImage:
            "linear-gradient(var(--aqt-border) 1px, transparent 1px), linear-gradient(90deg, var(--aqt-border) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
          WebkitMaskImage:
            "radial-gradient(120% 120% at 20% 0%, #000 35%, transparent 80%)",
          maskImage: "radial-gradient(120% 120% at 20% 0%, #000 35%, transparent 80%)",
        }}
      />
      {/* single restrained teal glow */}
      <span
        aria-hidden
        className="pointer-events-none absolute -left-[8%] -top-[30%] h-[150%] w-3/5"
        style={{ background: "var(--aqt-hero-glow)" }}
      />
      {/* profile-only role-tinted wash from the top-left corner */}
      {isProfile && roleTint ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background: `radial-gradient(70% 120% at 12% -20%, color-mix(in srgb, var(--aqt-${roleTint}) 16%, transparent), transparent 55%)`,
          }}
        />
      ) : null}
      <div className="relative z-[1]">{children}</div>
    </section>
  );
}

interface PageHeroProps {
  /** Mono coordinate line(s) above the title (use `HeroCoord`). */
  eyebrow?: React.ReactNode;
  /** Big mixed-case title. Wrap the accent word in `<em>` for the spectrum. */
  title: React.ReactNode;
  /** Optional supporting sentence under the title. */
  lede?: React.ReactNode;
  /** Optional pills/badges row directly under the title (status, format…). */
  meta?: React.ReactNode;
  /** Optional call-to-action buttons under the lede. */
  actions?: React.ReactNode;
  /** Optional right column — stat blocks, controls, a live-events panel. */
  aside?: React.ReactNode;
  /** Optional mono "stamp" row at the bottom of the left column. */
  stamp?: React.ReactNode;
  className?: string;
  titleClassName?: string;
  /** Vertical alignment of the two columns. */
  align?: "start" | "end" | "center";
}

export function PageHero({
  eyebrow,
  title,
  lede,
  meta,
  actions,
  aside,
  stamp,
  className,
  titleClassName,
  align = "end",
}: PageHeroProps) {
  return (
    <HeroFrame className={className}>
      <div
        className={cn(
          "grid gap-8 px-6 py-8 md:px-10 md:py-9",
          aside && "lg:grid-cols-[1.5fr_1fr] lg:gap-12",
          align === "end" && "lg:items-end",
          align === "center" && "lg:items-center",
          align === "start" && "lg:items-start"
        )}
      >
        <div className="min-w-0">
          {eyebrow ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">{eyebrow}</div>
          ) : null}
          <h1
            className={cn(
              "aqt-hero-title mt-4 font-onest text-[clamp(2rem,4.6vw,3.5rem)] font-semibold leading-[1.03] tracking-[-0.01em] text-[color:var(--aqt-fg)]",
              titleClassName
            )}
          >
            {title}
          </h1>
          {meta ? (
            <div className="mt-4 flex flex-wrap items-center gap-2">{meta}</div>
          ) : null}
          {lede ? (
            <p className="mt-5 max-w-[34rem] text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
              {lede}
            </p>
          ) : null}
          {actions ? (
            <div className="mt-6 flex flex-wrap items-center gap-2.5">{actions}</div>
          ) : null}
          {stamp ? (
            <div className="mt-7 flex flex-wrap gap-x-8 gap-y-3">{stamp}</div>
          ) : null}
        </div>
        {aside ? <div className="min-w-0">{aside}</div> : null}
      </div>
    </HeroFrame>
  );
}

/** Mono uppercase coordinate label — the tactical thread of the hero. */
export function HeroCoord({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-mono text-[12px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]",
        className
      )}
    >
      {children}
    </span>
  );
}

/** Mono stamp: a small uppercase label with a normal-case value beneath it. */
export function HeroStamp({
  label,
  value,
  valueClassName,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  valueClassName?: string;
}) {
  return (
    <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
      {label}
      <b
        className={cn(
          "mt-1 block text-[15px] font-semibold normal-case tracking-normal tabular-nums text-[color:var(--aqt-fg)]",
          valueClassName
        )}
      >
        {value}
      </b>
    </span>
  );
}

/** KPI stat block for the hero's right column. */
export function HeroStat({
  label,
  value,
  sub,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <span className="font-onest text-[clamp(1.7rem,2.2vw,2.15rem)] font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
        {value}
      </span>
      {sub ? <span className="text-[11px] text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
    </div>
  );
}
