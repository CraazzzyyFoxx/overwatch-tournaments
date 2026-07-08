"use client";

import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";

import { CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const ComparePageHeader = () => {
  const t = useTranslations();

  return (
    <CardHeader className="relative pb-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="text-2xl">{t("users.compare.title")}</CardTitle>
          <CardDescription>{t("users.compare.subtitle")}</CardDescription>
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={t("users.compare.guideAria")}
              className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-border/60 bg-background/20 text-muted-foreground transition-colors hover:bg-background/35 hover:text-foreground"
            >
              <CircleHelp className="h-4 w-4" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-90 max-w-[calc(100vw-2rem)]">
            <div className="space-y-2">
              <div className="text-sm font-semibold">{t("users.compare.guide.heading")}</div>
              <ol className="list-decimal space-y-1 pl-4 text-sm text-muted-foreground">
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
    </CardHeader>
  );
};

export default ComparePageHeader;
