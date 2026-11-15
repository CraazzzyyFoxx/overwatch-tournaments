"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type { UserMergeIdentityOption } from "@/types/admin.types";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig } from "@/lib/social/providers";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";

export function IdentitySelectionSection({
  label,
  items,
  selectedIds,
  onToggle
}: Readonly<{
  label: string;
  items: UserMergeIdentityOption[];
  selectedIds: number[];
  onToggle: (identityId: number, checked: boolean) => void;
}>) {
  const t = useTranslations("adminPeople.merge");
  const groupId = useId();

  if (items.length === 0) {
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">{label}</p>
        <EmptyNote>
          {t("noSocial")}
        </EmptyNote>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium" id={groupId}>
        {label}
      </p>
      <div className="divide-y divide-border/60" role="group" aria-labelledby={groupId}>
        {items.map((item) => {
          const checked = selectedIds.includes(item.id);
          const providerLabel = getSocialProviderConfig(item.provider).label;
          return (
            <div key={item.id} className="flex items-center gap-3 py-2">
              <Checkbox
                checked={checked}
                onCheckedChange={(state) => onToggle(item.id, state === true)}
                aria-label={t("move", { provider: providerLabel, value: item.value })}
              />
              <span title={providerLabel} className="inline-flex shrink-0">
                <SocialIcon provider={item.provider} size={14} />
              </span>
              <span className="truncate text-sm font-medium">{item.value}</span>
              {item.duplicate_on_target ? (
                <span className="text-caption text-muted-foreground">{t("duplicate")}</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
