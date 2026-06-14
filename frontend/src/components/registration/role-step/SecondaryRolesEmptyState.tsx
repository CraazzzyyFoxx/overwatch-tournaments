"use client";

import { useTranslation } from "@/i18n/LanguageContext";

export function SecondaryRolesEmptyState({ isFlex }: { isFlex: boolean }) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.015] px-3 py-3 text-sm text-white/42">
      {isFlex
        ? t("registration.roles.secondary.emptyStateFlex")
        : t("registration.roles.secondary.emptyStateChoosePrimary")}
    </div>
  );
}

