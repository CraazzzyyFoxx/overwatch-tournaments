"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";

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
    <Card className="flex flex-wrap items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className={eyebrowClass("muted")}>{eyebrow}</p>
        <p className="mt-0.5 text-sm font-medium text-foreground">{title}</p>
      </div>
      <Button asChild size="sm" className="shrink-0 gap-1.5">
        <Link href={href}>
          {cta}
          <ArrowRight aria-hidden />
        </Link>
      </Button>
    </Card>
  );
}
