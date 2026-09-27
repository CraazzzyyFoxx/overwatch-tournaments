"use client";

import { useTranslations } from "next-intl";

import { CategorizedColumnPicker } from "@/components/ui/categorized-column-picker";

import type { ColumnDefinition } from "./participantsColumns.model";
import { isMandatoryParticipantColumnId } from "./participants-url-state";

type ParticipantColumnCategory = ColumnDefinition["category"];

const CATEGORY_ORDER: readonly ParticipantColumnCategory[] = ["meta", "built_in", "custom"];

interface ColumnPickerProps {
  columns: ColumnDefinition[];
  visibility: Record<string, boolean>;
  onToggle: (id: string) => void;
  onReset: () => void;
}

export default function ColumnPicker({
  columns,
  visibility,
  onToggle,
  onReset,
}: Readonly<ColumnPickerProps>) {
  const t = useTranslations();

  const categoryLabel = (category: ParticipantColumnCategory): string => {
    switch (category) {
      case "meta":
        return t("tournamentDetail.columnCategory.general");
      case "built_in":
        return t("tournamentDetail.columnCategory.fields");
      case "custom":
        return t("tournamentDetail.columnCategory.customFields");
    }
  };

  return (
    <CategorizedColumnPicker<ParticipantColumnCategory, ColumnDefinition>
      columns={columns}
      categories={CATEGORY_ORDER}
      categoryLabel={categoryLabel}
      visibility={visibility}
      onToggle={onToggle}
      onReset={onReset}
      triggerLabel={t("common.columns")}
      resetLabel={t("tournamentDetail.resetColumns")}
      isMandatory={isMandatoryParticipantColumnId}
    />
  );
}
