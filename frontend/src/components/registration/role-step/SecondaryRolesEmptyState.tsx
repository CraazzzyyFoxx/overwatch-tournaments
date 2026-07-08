"use client";

import { useTranslations } from "next-intl";

export function SecondaryRolesEmptyState({ isFlex }: { isFlex: boolean }) {
  const t = useTranslations();

  return (
    <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.015] px-3 py-3 text-sm text-white/42">
      {isFlex
        ? t("registration.roles.secondary.emptyStateFlex")
        : t("registration.roles.secondary.emptyStateChoosePrimary")}
    </div>
  );
}

