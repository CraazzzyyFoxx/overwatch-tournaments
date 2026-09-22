import React from "react";

import { cn } from "@/lib/utils";
import type { PlayerRoleTint } from "@/lib/roster/player-role";

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

/** Role hue for the profile wash — maps to the `--aqt-{role}` role tokens.
 *  This is a PLAYER-role tint (Tank/Damage/Support/Flex), not a hero class; the
 *  name is historical, so it stays an alias over the one tint vocabulary. */
type HeroRoleTint = PlayerRoleTint;

/**
 * The cover wash's blur radius, and how far its image is bled past the frame.
 *
 * The bleed MUST stay comfortably over 3× the radius: a Gaussian blur reaches
 * roughly 3σ, and anything it samples from outside the image's own box is
 * transparent — which a `color` blend renders as no tint at all.
 */
const COVER_BLUR_PX = 28;
const COVER_BLEED_PX = 96;

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
  /**
   * Optional banner image behind the hero (a tournament cover) — rendered
   * BLURRED and full-bleed, as the tournament's colour field, not as a picture.
   *
   * Two earlier attempts read badly, both for the same reason:
   *
   * - Full-bleed and sharp: `object-cover` in a ~200px header crops a wide
   *   slice and the scrim hid the middle, so the organizer's centred key art
   *   was the one part never visible.
   * - An 80px sharp band: at 1568px wide that box is 19.6:1, and a 16:9 upload
   *   showed 9% of its own height — an arbitrary horizontal strip of legs and
   *   UI, recognisable as nothing.
   *
   * No crop of a poster survives those ratios, because the art is drawn to be
   * seen whole. It IS seen whole — on the tournaments list card (`aspect-video`,
   * the entire top of the card). What the detail header owes the reader is
   * recognition, not a second showing, and a colour field pulled from the same
   * image does that for any upload: 16:9, 3:1, or a portrait screenshot. The
   * logo beside the title carries the sharp identity.
   *
   * ## Why the blend and not a scrim
   *
   * `mix-blend-mode: color` takes hue and chroma from the image and LUMINANCE
   * from the frame underneath, so the header's brightness is by construction
   * the same as with no cover at all — every text contrast ratio is unchanged
   * and cannot be broken by an upload.
   *
   * An alpha scrim cannot do that. `--aqt-fg-faint` (the mono eyebrow, every
   * stat label) already sits at 5.1:1 on `--aqt-bg`, barely over the AA floor;
   * the arithmetic says a white cover bleeding through at even 5% drops it to
   * ~2.6:1, and the scrim that would save it (≈99%) shows nothing. So the tint
   * has to carry colour without carrying light.
   *
   * A desaturated (white/grey) cover therefore contributes nothing — correct
   * behaviour, not a bug: there is no palette in it to recognise.
   *
   * `scale-110` because a blur samples past the element's edges and would
   * otherwise leave a visible seam inside the frame. `isolate` on the section
   * keeps the blend inside the hero instead of reaching the page behind it.
   */
  coverUrl?: string | null;
  /**
   * `"right"` — sharp cover on the trailing edge, masked off toward the copy.
   * No colour-wash. Tournament detail uses this; every other hero keeps the
   * default wash when `coverUrl` is set.
   */
  coverFade?: "right";
}

/** The decorative shell only — for heroes with bespoke inner content. */
export function HeroFrame({
  children,
  className,
  variant = "default",
  roleTint,
  coverUrl,
  coverFade,
}: Readonly<HeroFrameProps>) {
  const isProfile = variant === "profile";
  const fadeRight = Boolean(coverUrl) && coverFade === "right";
  return (
    <section
      className={cn(
        "relative isolate overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]",
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
      {fadeRight ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={coverUrl ?? ""}
          alt=""
          aria-hidden
          loading="lazy"
          decoding="async"
          className="pointer-events-none absolute"
          /* Inline: mask/object utilities are easy to miss in this build, and a
             missing class fails silent — the poster then sizes the hero. */
          style={{
            top: 0,
            right: 0,
            bottom: 0,
            width: "min(58%, 36rem)",
            height: "100%",
            objectFit: "cover",
            objectPosition: "center",
            WebkitMaskImage: "linear-gradient(90deg, transparent 0%, #000 55%)",
            maskImage: "linear-gradient(90deg, transparent 0%, #000 55%)",
          }}
        />
      ) : coverUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={coverUrl}
          alt=""
          aria-hidden
          loading="lazy"
          decoding="async"
          className="pointer-events-none absolute object-cover"
          /* Inline rather than Tailwind utilities. `mix-blend-*`, `saturate-*`
             and inset-bleed are all new to this codebase here, and a class the
             build has not generated fails SILENTLY — the first render of this
             was a 70%-opaque photo, the exact brightness problem the blend
             exists to prevent. One style object cannot half-apply.

             `saturate` and not `opacity`: chroma is the only channel a `color`
             blend spends, and spending it is free — the frame's luminance, and
             with it every contrast ratio, is untouched however far it goes.

             `inset: -BLEED` and NOT `transform: scale`: a blur samples past the
             element's box and pulls TRANSPARENCY in from outside it, which the
             blend renders as "no tint". `scale(1.12)` on a 200px-tall header
             overhangs 12px against a ~84px blur reach, so the tint faded to 60%
             of itself at the top and bottom edges — a vignette that read as the
             image having come apart. The bleed is absolute, so it holds at any
             header height, unlike a ratio. */
          style={{
            inset: -COVER_BLEED_PX,
            mixBlendMode: "color",
            filter: `blur(${COVER_BLUR_PX}px) saturate(2.2)`,
          }}
        />
      ) : null}
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
  /**
   * Media column kisses the frame as a 20rem end-cap: no padding, no gap.
   * Copy keeps the padding. Not a 1fr split — that gave the poster half the hero.
   */
  asideFlush?: boolean;
  /** Optional mono "stamp" row at the bottom of the left column. */
  stamp?: React.ReactNode;
  className?: string;
  titleClassName?: string;
  /** Vertical alignment of the two columns. */
  align?: "start" | "end" | "center";
  /** Banner image behind the hero — see `HeroFrameProps.coverUrl`. */
  coverUrl?: string | null;
  /** See `HeroFrameProps.coverFade`. */
  coverFade?: "right";
  /**
   * Tight header for pages whose content starts right under it (a tournament's
   * section rail): half the padding, a ~2rem title, single-line rhythm. The
   * hero is then a header, not a landing block.
   */
  compact?: boolean;
}

export function PageHero({
  eyebrow,
  title,
  lede,
  meta,
  actions,
  aside,
  asideFlush = false,
  stamp,
  className,
  titleClassName,
  align = "end",
  coverUrl,
  coverFade,
  compact = false,
}: Readonly<PageHeroProps>) {
  const flush = Boolean(aside) && asideFlush;
  const pad = compact
    ? "px-5 py-3.5 md:px-6 md:py-4"
    : "px-6 py-8 md:px-10 md:py-9";

  return (
    <HeroFrame className={className} coverUrl={coverUrl} coverFade={coverFade}>
      <div
        className={cn(
          "grid",
          flush
            ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] lg:items-stretch"
            : cn(
                compact ? `gap-4 ${pad}` : `gap-8 ${pad}`,
                // A compact hero is a page HEADER: its right column holds the action
                // row (wireframes §2), so it takes only the width the buttons need
                // instead of a third of the header away from the title.
                aside &&
                  (compact
                    ? "lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-8"
                    : "lg:grid-cols-[1.5fr_1fr] lg:gap-12"),
                align === "end" && "lg:items-end",
                align === "center" && "lg:items-center",
                align === "start" && "lg:items-start"
              )
        )}
      >
        <div className={cn("min-w-0", flush && pad)}>
          {eyebrow ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">{eyebrow}</div>
          ) : null}
          <h1
            className={cn(
              "aqt-hero-title font-onest font-semibold text-[color:var(--aqt-fg)]",
              compact ? "mt-2 text-headline" : "mt-4 text-display",
              titleClassName
            )}
          >
            {title}
          </h1>
          {meta ? (
            <div className={cn("flex flex-wrap items-center gap-2", compact ? "mt-2.5" : "mt-4")}>
              {meta}
            </div>
          ) : null}
          {lede ? (
            <p
              className={cn(
                "max-w-[30rem] text-body text-[color:var(--aqt-fg-muted)]",
                compact ? "mt-2.5 max-w-[42rem]" : "mt-5"
              )}
            >
              {lede}
            </p>
          ) : null}
          {actions ? (
            /* `empty:hidden` because `actions` is often a fragment whose children
               each decide whether they render — an ended tournament with no links
               passes a truthy node that emits nothing, and the margin alone would
               leave a 24px hole under the lede. */
            <div
              className={cn(
                "flex flex-wrap items-center gap-2.5 empty:hidden",
                compact ? "mt-2.5" : "mt-6"
              )}
            >
              {actions}
            </div>
          ) : null}
          {stamp ? (
            <div
              className={cn(
                "flex flex-wrap items-end gap-x-8 gap-y-3",
                meta || lede || actions ? "mt-7" : "mt-3"
              )}
            >
              {stamp}
            </div>
          ) : null}
        </div>
        {aside ? (
          <div
            className={cn(
              "min-w-0",
              // Phone: the wash already tints the frame. A stacked 16:9 poster
              // under the title is the banner that ate the page.
              flush && "max-lg:hidden h-full lg:min-h-0"
            )}
          >
            {aside}
          </div>
        ) : null}
      </div>
    </HeroFrame>
  );
}

/** Mono uppercase coordinate label — the tactical thread of the hero. */
export function HeroCoord({
  children,
  className,
}: Readonly<{
  children: React.ReactNode;
  className?: string;
}>) {
  return (
    <span
      className={cn(
        "text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]",
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
}: Readonly<{
  label: React.ReactNode;
  value: React.ReactNode;
  valueClassName?: string;
}>) {
  return (
    <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
      {label}
      <b
        className={cn(
          "mt-1 block text-ui font-semibold normal-case tracking-normal tabular-nums text-[color:var(--aqt-fg)]",
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
}: Readonly<{
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
}>) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <span className="font-onest text-[clamp(1.7rem,2.2vw,2.15rem)] font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
        {value}
      </span>
      {sub ? <span className="text-label text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
    </div>
  );
}
