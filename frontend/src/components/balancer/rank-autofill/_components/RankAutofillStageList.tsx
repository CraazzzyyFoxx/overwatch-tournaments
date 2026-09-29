"use client";

import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  STAGE_WINDOW_KIND,
  stageWindowValue
} from "../rank-autofill-stages";
import { TONE_TEXT } from "@/components/kit/tone";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDragSensors } from "@/hooks/useDragSensors";
import { cn } from "@/lib/utils";
import type {
  RankAutofillOwValue,
  RankAutofillSourceKey,
  RegistrationRankAutofillStage
} from "@/types/balancer-admin.types";

const OW_VALUES: RankAutofillOwValue[] = ["composite", "current", "peak"];

interface RankAutofillStageListProps {
  stages: RegistrationRankAutofillStage[];
  disabled?: boolean;
  onReorder: (activeSource: RankAutofillSourceKey, overSource: RankAutofillSourceKey) => void;
  onToggle: (source: RankAutofillSourceKey, enabled: boolean) => void;
  onLookbackChange: (source: RankAutofillSourceKey, value: number | null) => void;
  onOwValueChange: (value: RankAutofillOwValue) => void;
}

interface SortableStageRowProps {
  stage: RegistrationRankAutofillStage;
  index: number;
  disabled: boolean;
  onToggle: (source: RankAutofillSourceKey, enabled: boolean) => void;
  onLookbackChange: (source: RankAutofillSourceKey, value: number | null) => void;
  onOwValueChange: (value: RankAutofillOwValue) => void;
}

function SortableStageRow({
  stage,
  index,
  disabled,
  onToggle,
  onLookbackChange,
  onOwValueChange
}: Readonly<SortableStageRowProps>) {
  const t = useTranslations();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: stage.source
  });
  const windowKind = STAGE_WINDOW_KIND[stage.source];
  const windowValue = stageWindowValue(stage);
  const label = t(`rankAutofill.source.${stage.source}.label`);
  const owValue = stage.source === "ow" ? (stage.ow_value ?? "composite") : null;
  // The OW row describes the number it offers; the others describe their source.
  const description =
    stage.source === "ow"
      ? t(`rankAutofill.owValue.${stage.ow_value ?? "composite"}.description`)
      : t(`rankAutofill.source.${stage.source}.description`);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5",
        isDragging && "z-10 opacity-80 shadow-lg shadow-black/40",
        !stage.enabled && "opacity-55"
      )}
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          className="cursor-grab touch-none text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg-muted)] disabled:cursor-not-allowed"
          aria-label={t("rankAutofill.dragAria")}
          disabled={disabled}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>

        <span className="w-4 shrink-0 text-center text-xs font-semibold tabular-nums text-[color:var(--aqt-fg-dim)]">
          {index + 1}
        </span>

        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-[color:var(--aqt-fg)]">{label}</div>
          <div className="truncate text-xs text-[color:var(--aqt-fg-dim)]">{description}</div>
        </div>

        {owValue && (
          <Select
            value={owValue}
            disabled={disabled}
            onValueChange={(next) => onOwValueChange(next as RankAutofillOwValue)}
          >
            <SelectTrigger aria-label={t("rankAutofill.owValueAria")} className="h-8 w-32 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OW_VALUES.map((value) => (
                <SelectItem key={value} value={value} className="text-xs">
                  {t(`rankAutofill.owValue.${value}.label`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <label className="flex shrink-0 items-center gap-1.5">
          <NumberInput
            integer
            min={1}
            value={windowValue}
            placeholder={t(`rankAutofill.window.${windowKind}Placeholder`)}
            // The latest rank is the latest rank: no window narrows it.
            disabled={disabled || owValue === "current"}
            onValueChange={(next) => onLookbackChange(stage.source, next)}
            className="h-8 w-16 text-right text-xs"
            aria-label={t("rankAutofill.windowAria", { label })}
          />
          <span className="w-9 text-xs text-[color:var(--aqt-fg-dim)]">
            {t(`rankAutofill.window.${windowKind}Suffix`)}
          </span>
        </label>

        <Switch
          checked={stage.enabled}
          disabled={disabled}
          onCheckedChange={(checked) => onToggle(stage.source, checked === true)}
          aria-label={t("rankAutofill.enableAria", { label })}
        />
      </div>

      {owValue === "peak" && (
        <p className={cn("flex items-start gap-1.5 pl-11 text-xs leading-4", TONE_TEXT.warning)}>
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("rankAutofill.owValue.peak.caveat")}
        </p>
      )}
    </div>
  );
}

export function RankAutofillStageList({
  stages,
  disabled = false,
  onReorder,
  onToggle,
  onLookbackChange,
  onOwValueChange
}: Readonly<RankAutofillStageListProps>) {
  const sensors = useDragSensors({ distance: 4, keyboard: true });

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    onReorder(active.id as RankAutofillSourceKey, over.id as RankAutofillSourceKey);
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={stages.map((stage) => stage.source)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-2">
          {stages.map((stage, index) => (
            <SortableStageRow
              key={stage.source}
              stage={stage}
              index={index}
              disabled={disabled}
              onToggle={onToggle}
              onLookbackChange={onLookbackChange}
              onOwValueChange={onOwValueChange}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
