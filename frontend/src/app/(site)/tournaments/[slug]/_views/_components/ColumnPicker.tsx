"use client";

import { Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";

import type { ColumnDefinition } from "./participantsColumns.model";
import { isMandatoryParticipantColumnId } from "./participants-url-state";

type ParticipantColumnCategory = ColumnDefinition["category"];

const CATEGORY_ORDER: readonly ParticipantColumnCategory[] = ["meta", "built_in", "custom"];

const CATEGORY_LABEL_KEY = {
  meta: "tournamentDetail.columnCategory.general",
  built_in: "tournamentDetail.columnCategory.fields",
  custom: "tournamentDetail.columnCategory.customFields"
} as const satisfies Record<ParticipantColumnCategory, string>;

interface ColumnPickerProps {
  columns: ColumnDefinition[];
  visibility: Record<string, boolean>;
  onToggle: (id: string) => void;
  onReset: () => void;
}

/**
 * The participants table's "Columns" menu: columns grouped by category, the
 * mandatory ones checked and locked. The admin tables' view menu reads the same.
 */
export default function ColumnPicker({ columns, visibility, onToggle, onReset }: Readonly<ColumnPickerProps>) {
  const t = useTranslations();

  return (
    <DropdownMenu>
      {/* 40px below `sm`, like every control of the participants toolbar it sits in. */}
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="max-sm:h-10">
          <Settings2 aria-hidden />
          {t("common.columns")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {CATEGORY_ORDER.map((category) => {
          const items = columns.filter((column) => column.category === category);
          if (items.length === 0) return null;
          return (
            <DropdownMenuGroup key={category}>
              <DropdownMenuLabel>{t(CATEGORY_LABEL_KEY[category])}</DropdownMenuLabel>
              {items.map((column) => {
                const mandatory = isMandatoryParticipantColumnId(column.id);
                return (
                  <DropdownMenuCheckboxItem
                    key={column.id}
                    checked={mandatory || visibility[column.id] !== false}
                    disabled={mandatory}
                    onCheckedChange={() => onToggle(column.id)}
                    // Stay open: columns are toggled several at a time.
                    onSelect={(event) => event.preventDefault()}
                  >
                    {column.label}
                  </DropdownMenuCheckboxItem>
                );
              })}
            </DropdownMenuGroup>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            onReset();
          }}
        >
          {t("tournamentDetail.resetColumns")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
