"use client";

import React from "react";
import { Globe } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";

import { setUserLocale } from "@/i18n/locale-actions";
import type { Locale } from "@/i18n/resolve-locale";
import { Button } from "./ui/button";

export default function LanguageSwitcher() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const router = useRouter();

  const toggleLocale = () => {
    const next: Locale = locale === "en" ? "ru" : "en";
    void setUserLocale(next).then(() => router.refresh());
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-8 gap-1.5 rounded-lg border-white/10 px-2.5 text-xs font-semibold text-white/70 hover:bg-white/4 hover:text-white"
      onClick={toggleLocale}
      title={t("common.switchLanguage")}
    >
      <Globe className="h-3.5 w-3.5 opacity-60" />
      <span className="uppercase">{locale}</span>
    </Button>
  );
}
