"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { SettingGroup } from "@/components/kit/SettingRow";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";

/**
 * How a stage's matches are played and ranked, as one card: the series length, the points a result pays and
 * the tiebreakers. Each part was a card of its own, three thin cards that fed the same save.
 */
export function ScoringSection({ children }: Readonly<{ children: ReactNode }>) {
  const tRoot = useTranslations("adminBracket");
  return (
    <SettingGroup id="stage-scoring" title={tRoot("editor.scoring")}>
      {children}
    </SettingGroup>
  );
}

/** One titled part of `ScoringSection`; its rows keep the card's hairlines between them. */
export function ScoringPart({
  title,
  description,
  children
}: Readonly<{ title: string; description?: ReactNode; children: ReactNode }>) {
  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <h3 className={eyebrowClass("muted")}>{title}</h3>
      {description ? <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">{description}</p> : null}
      <div className="mt-3 divide-y divide-border/60">{children}</div>
    </div>
  );
}
