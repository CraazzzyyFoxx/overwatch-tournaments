"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

export interface NextActionHeroProps {
  eyebrow: string;
  title: ReactNode;
  href: string;
  cta: string;
}

/**
 * The one thing worth doing next (F1 ·2, F3 ·3).
 *
 * Replaces a grid of seven equally-weighted issue tiles: the same data, but
 * ranked, because an operator opening the dashboard wants a decision, not an
 * inventory. Rendered from the first open item of `buildChecklist`.
 */
export function NextActionHero({ eyebrow, title, href, cta }: Readonly<NextActionHeroProps>) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className={cn(EYEBROW_CLASS, "text-primary/80")}>{eyebrow}</p>
        <p className="mt-0.5 text-sm font-medium text-foreground">{title}</p>
      </div>
      <Link
        href={href}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground",
          "transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        {cta}
        <ArrowRight aria-hidden className="size-3.5" />
      </Link>
    </div>
  );
}
