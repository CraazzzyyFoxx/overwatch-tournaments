"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";

import { SortableGrip, useSortableRow } from "@/components/kit/SortableRows";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { FormSection } from "@/types/forms.types";

/** dnd-kit ids are one flat namespace, so each kind carries its own prefix. */
export const SECTION_DRAG_PREFIX = "section:";
export const FIELD_DRAG_PREFIX = "field:";

function SectionRow({
  section,
  index,
  selected,
  deletable,
  onSelect,
  onDelete
}: Readonly<{
  section: FormSection;
  index: number;
  selected: boolean;
  deletable: boolean;
  onSelect: () => void;
  onDelete: () => void;
}>) {
  const t = useTranslations("registrationFormAdmin.builder");
  const { ref, style, handleProps, isDragging } = useSortableRow(
    `${SECTION_DRAG_PREFIX}${section.key}`
  );
  const title = section.title?.trim() || t("sectionFallback", { index: index + 1 });

  return (
    <li
      ref={ref}
      style={style}
      className={cn(
        "flex items-center gap-2 rounded-lg border px-2 py-1.5",
        selected ? "border-primary/40 bg-primary/10" : "border-border/60",
        isDragging && "opacity-90"
      )}
    >
      <SortableGrip handleProps={handleProps} label={t("reorderSection", { section: title })} />
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className="min-w-0 flex-1 text-left"
      >
        <span className="block truncate text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-foreground">
          {t("fieldCount", { count: section.fields.length })}
        </span>
      </button>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 shrink-0"
        disabled={!deletable}
        title={deletable ? t("deleteSection") : t("deleteSectionBlocked")}
        aria-label={
          deletable
            ? t("deleteSectionAria", { section: title })
            : t("deleteSectionBlockedAria", { section: title })
        }
        onClick={onDelete}
      >
        <Trash2 className="size-3.5" aria-hidden />
      </Button>
    </li>
  );
}

/**
 * The section rail: what the wizard's steps are, in order.
 *
 * Each row is also the drop target that moves a field into another section —
 * that is why the rail and the field list share one `DndContext` up in the
 * builder. A section is only deletable while empty: deleting one with fields
 * in it would silently drop questions (and, with them, the answers already
 * filed under their keys), and "are you sure" is a worse answer than "move
 * them out first".
 */
export function SectionList({
  sections,
  selectedKey,
  onSelect,
  onAdd,
  onDelete
}: Readonly<{
  sections: FormSection[];
  selectedKey: string;
  onSelect: (key: string) => void;
  onAdd: () => void;
  onDelete: (key: string) => void;
}>) {
  const t = useTranslations("registrationFormAdmin.builder");

  return (
    <div className="flex w-full shrink-0 flex-col gap-2 rounded-xl border border-border bg-card p-3 md:w-64">
      <h3 className={EYEBROW_CLASS}>{t("sections")}</h3>
      <SortableContext
        items={sections.map((section) => `${SECTION_DRAG_PREFIX}${section.key}`)}
        strategy={verticalListSortingStrategy}
      >
        <ul role="list" className="flex flex-col gap-1.5">
          {sections.map((section, index) => (
            <SectionRow
              key={section.key}
              section={section}
              index={index}
              selected={section.key === selectedKey}
              // The last section can never go: a schema needs at least one.
              deletable={section.fields.length === 0 && sections.length > 1}
              onSelect={() => onSelect(section.key)}
              onDelete={() => onDelete(section.key)}
            />
          ))}
        </ul>
      </SortableContext>
      <Button variant="outline" size="sm" className="justify-start" onClick={onAdd}>
        <Plus className="mr-1.5 size-3.5" aria-hidden />
        {t("addSection")}
      </Button>
    </div>
  );
}
