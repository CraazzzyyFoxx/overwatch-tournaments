"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  STAGE_WINDOW_KIND,
  parseLookbackInput,
  stageWindowValue
} from "@/app/balancer/components/rank-autofill-stages";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type {
  RankAutofillSourceKey,
  RegistrationRankAutofillStage
} from "@/types/balancer-admin.types";

interface RankAutofillStageListProps {
  stages: RegistrationRankAutofillStage[];
  disabled?: boolean;
  onReorder: (activeSource: RankAutofillSourceKey, overSource: RankAutofillSourceKey) => void;
  onToggle: (source: RankAutofillSourceKey, enabled: boolean) => void;
  onLookbackChange: (source: RankAutofillSourceKey, value: number | null) => void;
}

interface SortableStageRowProps {
  stage: RegistrationRankAutofillStage;
  index: number;
  disabled: boolean;
  onToggle: (source: RankAutofillSourceKey, enabled: boolean) => void;
  onLookbackChange: (source: RankAutofillSourceKey, value: number | null) => void;
}

function SortableStageRow({
  stage,
  index,
  disabled,
  onToggle,
  onLookbackChange
}: SortableStageRowProps) {
  const t = useTranslations();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: stage.source
  });
  const windowKind = STAGE_WINDOW_KIND[stage.source];
  const windowValue = stageWindowValue(stage);
  const label = t(`rankAutofill.source.${stage.source}.label`);
  const description = t(`rankAutofill.source.${stage.source}.description`);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5",
        isDragging && "z-10 opacity-80 shadow-lg shadow-black/40",
        !stage.enabled && "opacity-55"
      )}
    >
      <button
        type="button"
        className="cursor-grab touch-none text-white/30 hover:text-white/60 disabled:cursor-not-allowed"
        aria-label={t("rankAutofill.dragAria")}
        disabled={disabled}
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>

      <span className="w-4 shrink-0 text-center text-xs font-semibold tabular-nums text-white/35">
        {index + 1}
      </span>

      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-white/85">{label}</div>
        <div className="truncate text-[11px] text-white/40">{description}</div>
      </div>

      <label className="flex shrink-0 items-center gap-1.5">
        <Input
          type="number"
          min={1}
          inputMode="numeric"
          value={windowValue ?? ""}
          placeholder={t(`rankAutofill.window.${windowKind}Placeholder`)}
          disabled={disabled}
          onChange={(event) => onLookbackChange(stage.source, parseLookbackInput(event.target.value))}
          className="h-8 w-16 text-right text-xs"
          aria-label={t("rankAutofill.windowAria", { label })}
        />
        <span className="w-9 text-[11px] text-white/40">
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
  );
}

export function RankAutofillStageList({
  stages,
  disabled = false,
  onReorder,
  onToggle,
  onLookbackChange
}: RankAutofillStageListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

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
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
