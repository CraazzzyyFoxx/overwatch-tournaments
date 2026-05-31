"use client";

import React from "react";
import { Globe } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";
import { Button } from "./ui/button";

export default function LanguageSwitcher() {
  const { locale, setLocale } = useTranslation();

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-8 gap-1.5 rounded-lg border-white/10 px-2.5 text-xs font-semibold text-white/70 hover:bg-white/4 hover:text-white"
      onClick={() => setLocale(locale === "en" ? "ru" : "en")}
      title={locale === "en" ? "Switch to Russian" : "Переключить на английский"}
    >
      <Globe className="h-3.5 w-3.5 opacity-60" />
      <span className="uppercase">{locale}</span>
    </Button>
  );
}
