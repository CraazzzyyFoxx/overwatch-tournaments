"use client";

import { useTranslations } from "next-intl";

export function SecondaryRolesEmptyState({ isFlex }: { isFlex: boolean }) {
  const t = useTranslations();

  return (
    <div className="rounded-xl border border-dashed border-[color:var(--aqt-border-2)] bg-white/[0.015] px-3 py-3 text-sm text-[color:var(--aqt-fg-dim)]">
      {isFlex
        ? t("registration.roles.secondary.emptyStateFlex")
        : t("registration.roles.secondary.emptyStateChoosePrimary")}
    </div>
  );
}

