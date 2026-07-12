"use client";

import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const ComparePageHeader = () => {
  const t = useTranslations();

  return (
    <div className="flex items-start justify-between gap-3">
      <div className="space-y-1">
        <h1 className="aqt-display text-2xl font-bold tracking-tight text-[color:var(--aqt-fg)]">
          {t("users.compare.title")}
        </h1>
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("users.compare.subtitle")}</p>
      </div>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={t("users.compare.guideAria")}
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[hsl(0_0%_100%/0.04)] hover:text-[color:var(--aqt-fg)]"
          >
            <CircleHelp className="h-4 w-4" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-90 max-w-[calc(100vw-2rem)]">
          <div className="space-y-2">
            <div className="aqt-display text-sm font-bold text-[color:var(--aqt-fg)]">
              {t("users.compare.guide.heading")}
            </div>
            <ol className="list-decimal space-y-1 pl-4 text-sm text-[color:var(--aqt-fg-muted)]">
              <li>{t("users.compare.guide.step1")}</li>
              <li>{t("users.compare.guide.step2")}</li>
              <li>{t("users.compare.guide.step3")}</li>
              <li>{t("users.compare.guide.step4")}</li>
              <li>{t("users.compare.guide.step5")}</li>
              <li>{t("users.compare.guide.step6")}</li>
            </ol>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default ComparePageHeader;
