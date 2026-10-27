"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type {
  UserMergeFieldChoice,
  UserMergeFieldPolicy,
  UserMergePreviewResponse
} from "@/types/admin.types";
import Image from "@/components/ui/image";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export type FieldKey = keyof UserMergeFieldPolicy;

export function FieldChoiceButtons({
  label,
  fieldKey,
  preview,
  value,
  sourceName,
  targetName,
  onChange
}: Readonly<{
  label: string;
  fieldKey: FieldKey;
  preview: UserMergePreviewResponse;
  value: UserMergeFieldChoice;
  sourceName: string;
  targetName: string;
  onChange: (value: UserMergeFieldChoice) => void;
}>) {
  const t = useTranslations("adminPeople.merge");
  const groupId = useId();
  const options = [
    ["source", sourceName, preview.field_options[fieldKey].source],
    ["target", targetName, preview.field_options[fieldKey].target]
  ] as const;

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium" id={groupId}>{label}</p>
      <ToggleGroup
        variant="card"
        className="grid-cols-2"
        aria-labelledby={groupId}
        value={value}
        onValueChange={(next) => onChange(next as UserMergeFieldChoice)}
      >
        {options.map(([choice, caption, raw]) => {
          const photo = fieldKey === "avatar_url" && raw && /^https?:\/\//.test(raw) ? raw : null;
          return (
            <ToggleGroupItem key={choice} value={choice}>
              <span className="block truncate text-xs">{caption}</span>
              {photo ? (
                <Image src={photo} alt="" width={32} height={32} className="h-8 w-8 rounded-full object-cover" />
              ) : (
                <span className="block truncate text-sm">{raw || t("none")}</span>
              )}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
    </div>
  );
}
