"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import type { GlossaryTerm } from "@/disciplines/overwatch/analytics/analytics-glossary";

interface InfoDotProps {
  term: GlossaryTerm;
  /** Opens the term's glossary sheet: the tap path, since a tooltip never opens on touch. */
  onExplain?: (term: GlossaryTerm) => void;
}

/**
 * The explainer beside a metric: hover or focus shows the one-line glossary
 * entry, a click or tap opens the full one. `-my-2` keeps the 28px hit box from
 * growing the line it sits on.
 */
export default function InfoDot({ term, onExplain }: Readonly<InfoDotProps>) {
  const t = useTranslations();
  const label = t(`analytics.glossary.${term}.label`);
  const plain = t(`analytics.glossary.${term}.plain`);

  if (!onExplain) {
    return (
      <IconTooltip label={label} hint={plain} className="align-middle">
        <Info aria-hidden className="size-3.5" />
      </IconTooltip>
    );
  }

  return (
    <IconTooltip label={label} hint={plain} control className="-my-2 align-middle">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={label}
        onClick={(event) => {
          event.stopPropagation();
          onExplain(term);
        }}
      >
        <Info aria-hidden />
      </Button>
    </IconTooltip>
  );
}
