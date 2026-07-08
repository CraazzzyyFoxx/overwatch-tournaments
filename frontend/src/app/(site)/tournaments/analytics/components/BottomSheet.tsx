"use client";

import React from "react";

import { useTranslations } from "next-intl";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";

export type SheetState = { kind: "term"; term: GlossaryTerm } | { kind: "how" };

interface BottomSheetProps {
  state: SheetState | null;
  onClose: () => void;
}

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-primary">
      {children}
    </span>
  );
}

function TermBody({ term }: { term: GlossaryTerm }) {
  const t = useTranslations();
  return (
    <SheetHeader>
      <Kicker>{t("analytics.sheet.glossaryKicker")}</Kicker>
      <SheetTitle className="text-xl">{t(`analytics.glossary.${term}.label`)}</SheetTitle>
      <SheetDescription className="text-sm leading-relaxed">
        {t(`analytics.glossary.${term}.plain`)}
      </SheetDescription>
    </SheetHeader>
  );
}

function HowBody() {
  const t = useTranslations();
  const steps = [1, 2, 3] as const;
  return (
    <>
      <SheetHeader>
        <Kicker>{t("analytics.howItWorks.kicker")}</Kicker>
        <SheetTitle className="text-xl">{t("analytics.howItWorks.title")}</SheetTitle>
        <SheetDescription className="text-sm leading-relaxed">
          {t("analytics.howItWorks.intro")}
        </SheetDescription>
      </SheetHeader>
      <div className="mt-4 flex flex-col gap-4">
        {steps.map((step) => (
          <div className="flex items-start gap-3" key={step}>
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-primary/15 text-sm font-bold text-primary">
              {step}
            </span>
            <span>
              <span className="block text-[15px] font-semibold text-foreground">
                {t(`analytics.howItWorks.step${step}Title`)}
              </span>
              <span className="mt-0.5 block text-sm leading-relaxed text-muted-foreground">
                {t(`analytics.howItWorks.step${step}Body`)}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[13px] italic text-muted-foreground">
        {t("analytics.howItWorks.foot")}
      </p>
    </>
  );
}

/**
 * Glossary / how-it-works explainer, built on the shadcn Sheet (a bottom
 * drawer). It only mounts while open (Radix portal), so nothing lingers in the
 * DOM when closed. Opened by info dots, dotted terms and the help card.
 */
export default function BottomSheet({ state, onClose }: BottomSheetProps) {
  return (
    <Sheet
      open={state != null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        side="bottom"
        className="mx-auto max-h-[85vh] max-w-lg overflow-y-auto rounded-t-2xl"
      >
        {state?.kind === "term" ? <TermBody term={state.term} /> : null}
        {state?.kind === "how" ? <HowBody /> : null}
      </SheetContent>
    </Sheet>
  );
}
