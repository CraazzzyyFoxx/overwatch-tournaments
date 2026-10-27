"use client";

import { useId, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { MoreLink } from "@/components/site/open-layout";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { RowButton } from "@/components/ui/row-button";
import { cn } from "@/lib/utils";

import "./more-features.css";

export interface MoreFeature {
  key: string;
  icon: ReactNode;
  title: string;
  text: string;
  /** The docs article that sets it up. */
  href: string;
  /** A real production capture. */
  src: string;
  width: number;
  height: number;
  alt: string;
}

/** A lit tile with the stat tiles' soft teal glow under the pointer (DESIGN.md §5, game polish). */
const TILE_CLASS = cn(
  "group relative isolate flex min-w-0 flex-col overflow-hidden rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] p-5",
  "bg-[radial-gradient(130%_120%_at_0%_0%,var(--aqt-card-2),var(--aqt-card)_62%)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)]",
  "before:pointer-events-none before:absolute before:inset-0 before:-z-10 before:bg-[radial-gradient(55%_60%_at_100%_0%,color-mix(in_srgb,var(--aqt-teal)_9%,transparent),transparent_70%)]",
  "transition-[border-color,box-shadow] duration-300",
  "hover:border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] hover:shadow-[inset_0_1px_0_var(--aqt-overlay-4),0_24px_50px_-32px_color-mix(in_srgb,var(--aqt-teal)_60%,transparent)]"
);

/** The open tile takes the large slot: the first row on a tablet, two columns by two rows from 1024px. */
const OPEN_CLASS = "sm:col-span-2 sm:row-start-1 lg:col-[1/span_2] lg:row-[1/span_2]";

const ICON_CLASS = cn(
  "grid size-9.5 shrink-0 place-items-center rounded-[10px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-faint)] transition-[color,background-color,border-color,box-shadow] duration-300 [&_svg]:size-4.5",
  "group-hover:text-[color:var(--aqt-teal)]"
);

const ICON_OPEN_CLASS =
  "border-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)] shadow-[0_0_22px_-6px_color-mix(in_srgb,var(--aqt-teal)_70%,transparent)]";

/**
 * What the organizer tour does not show, as a bento (an accordion with one
 * panel always open): the open feature takes the large slot with its real
 * screenshot and its docs link; every other one is a small tile whose title
 * opens it. The swap runs in a view transition (`more-features.css`), so the
 * tiles morph to their new boxes; without the API or under reduced motion it
 * lands at once. The DOM order never changes, so focus stays on the tile just
 * picked and a phone opens it in place.
 */
export function MoreFeatures({
  features,
  labels
}: Readonly<{
  features: readonly MoreFeature[];
  labels: { title: string; docs: string; howTo: string };
}>) {
  const id = useId();
  const [open, setOpen] = useState(features[0]?.key);

  const pick = (key: string) => {
    if (key === open) return;
    if (typeof document.startViewTransition !== "function" || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setOpen(key);
      return;
    }
    // The old frame is what is on screen now; the callback renders the new one synchronously for the second capture.
    document.startViewTransition(() => {
      flushSync(() => setOpen(key));
    });
  };

  return (
    <div className="mt-[clamp(20px,2.5vw,28px)]">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
        <Eyebrow as="h3" id={`${id}-title`}>
          {labels.title}
        </Eyebrow>
        <MoreLink href="/docs">{labels.docs}</MoreLink>
      </div>
      <ul
        data-gw-more
        aria-labelledby={`${id}-title`}
        className="mt-2 grid grid-flow-row-dense grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:grid-rows-[repeat(2,minmax(196px,auto))]"
      >
        {features.map((feature) => {
          const isOpen = feature.key === open;
          const buttonId = `${id}-${feature.key}`;
          const panelId = `${buttonId}-panel`;
          return (
            <li
              key={feature.key}
              style={{ viewTransitionName: `gw-more-${feature.key}` }}
              className={cn(TILE_CLASS, isOpen && OPEN_CLASS)}
            >
              <div className="flex items-start justify-between gap-3">
                <span aria-hidden className={cn(ICON_CLASS, isOpen && ICON_OPEN_CLASS)}>
                  {feature.icon}
                </span>
                {isOpen ? null : (
                  // Above the title's stretched hit area, so the docs stay one click away from a closed tile.
                  <Link
                    href={feature.href}
                    prefetch={false}
                    aria-label={`${labels.howTo}: ${feature.title}`}
                    title={labels.howTo}
                    className="relative z-[1] -mr-1.5 -mt-1.5 grid size-8 place-items-center rounded-md text-[color:var(--aqt-fg-faint)] transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-[color:var(--aqt-teal)]"
                  >
                    <ArrowRight className="size-4" aria-hidden />
                  </Link>
                )}
              </div>
              <h4 className="mt-3.5">
                <RowButton
                  id={buttonId}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  // An accordion that always keeps one panel open: the open one's header cannot close it.
                  aria-disabled={isOpen || undefined}
                  onClick={() => pick(feature.key)}
                  className={cn(
                    "w-auto text-balance font-display text-heading font-semibold text-[color:var(--aqt-fg)] hover:bg-transparent aria-disabled:cursor-default",
                    "after:absolute after:inset-0 after:rounded-[var(--aqt-radius)] after:content-['']",
                    "focus-visible:ring-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[color:var(--aqt-teal)]"
                  )}
                >
                  {feature.title}
                </RowButton>
              </h4>
              <p className="mt-1.5 text-pretty text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
                {feature.text}
              </p>
              <div
                id={panelId}
                role="region"
                aria-labelledby={buttonId}
                hidden={!isOpen}
                className={isOpen ? "flex min-h-0 flex-1 flex-col" : undefined}
              >
                {isOpen ? (
                  <>
                    <MoreLink href={feature.href} className="relative z-[1] mt-2 self-start">
                      {labels.howTo}
                    </MoreLink>
                    <div className="relative -mb-5 -mr-5 mt-3 aspect-[16/10] overflow-hidden rounded-tl-xl border-l border-t border-[color:var(--aqt-border-2)] sm:aspect-auto sm:min-h-[220px] sm:flex-1">
                      <Image
                        src={feature.src}
                        width={feature.width}
                        height={feature.height}
                        sizes="(min-width: 1024px) 640px, 100vw"
                        alt={feature.alt}
                        className="aqt-zoom absolute inset-0 size-full object-cover object-left-top"
                      />
                    </div>
                  </>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
