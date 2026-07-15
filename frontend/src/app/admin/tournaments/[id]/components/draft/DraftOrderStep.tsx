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
import { Dices, GripVertical, LockKeyhole, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftCaptainOrder, DraftFormat } from "@/types/draft.types";

import { moveCaptain, orderCaptainIds } from "./setup-model";
import { DraftSetupPreview } from "./DraftSetupPreview";
import type { DraftCaptainSetup } from "./setup-types";
import { registrationLabel, summarizeRegistration } from "./setup-types";

interface DraftOrderStepProps {
  value: DraftCaptainSetup;
  onChange: (next: DraftCaptainSetup) => void;
  pool: AdminRegistration[];
  rounds: number;
  format: DraftFormat;
  roundRules: string[];
}

export function DraftOrderStep({
  value,
  onChange,
  pool,
  rounds,
  format,
  roundRules
}: DraftOrderStepProps) {
  const t = useTranslations("draftAdmin");
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const ranks = new Map(
    pool.map((registration) => [registration.id, summarizeRegistration(registration).rank])
  );
  const orderedIds = orderCaptainIds(value.ids, value.order, ranks, value.randomSeed);

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    onChange({
      ...value,
      ids: moveCaptain(value.ids, Number(active.id), Number(over.id))
    });
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div className="space-y-2">
          <label htmlFor="captain-order" className="text-sm font-medium">
            {t("captainOrder")}
          </label>
          <Select
            value={value.order}
            onValueChange={(order) => onChange({ ...value, order: order as DraftCaptainOrder })}
          >
            <SelectTrigger id="captain-order">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="weakest_first">{t("orders.weakest_first.title")}</SelectItem>
              <SelectItem value="strongest_first">{t("orders.strongest_first.title")}</SelectItem>
              <SelectItem value="random">{t("orders.random.title")}</SelectItem>
              <SelectItem value="manual">{t("orders.manual.title")}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-sm text-muted-foreground">{t(`orders.${value.order}.description`)}</p>
        </div>
        {value.order === "random" && (
          <div className="flex items-center gap-2 rounded-xl border border-border/70 bg-muted/20 px-3 py-2">
            <LockKeyhole className="h-4 w-4 text-muted-foreground" />
            <span className="font-mono text-xs">{value.randomSeed}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() =>
                onChange({ ...value, randomSeed: Math.floor(Math.random() * 2_147_483_647) })
              }
              aria-label={t("newRandomSeed")}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>

      {value.order === "manual" ? (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={value.ids} strategy={verticalListSortingStrategy}>
            <div className="space-y-2">
              {value.ids.map((id, index) => {
                const registration = pool.find((candidate) => candidate.id === id);
                if (!registration) return null;
                return (
                  <SortableCaptain
                    key={id}
                    id={id}
                    position={index + 1}
                    label={registrationLabel(registration)}
                    rank={summarizeRegistration(registration).rank}
                  />
                );
              })}
            </div>
          </SortableContext>
        </DndContext>
      ) : (
        <div className="space-y-2">
          {orderedIds.map((id, index) => {
            const registration = pool.find((candidate) => candidate.id === id);
            if (!registration) return null;
            return (
              <div
                key={id}
                className="flex items-center gap-3 rounded-xl border border-border/70 bg-card px-4 py-3"
              >
                <Badge className="grid h-7 w-7 place-items-center rounded-full p-0">{index + 1}</Badge>
                {value.order === "random" ? (
                  <Dices className="h-4 w-4 text-muted-foreground" />
                ) : null}
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {registrationLabel(registration)}
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {summarizeRegistration(registration).rank ?? "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <DraftSetupPreview
        orderedCaptainIds={orderedIds}
        pool={pool}
        rounds={rounds}
        format={format}
        roundRules={roundRules}
      />
    </div>
  );
}

interface SortableCaptainProps {
  id: number;
  position: number;
  label: string;
  rank: number | null;
}

function SortableCaptain({ id, position, label, rank }: SortableCaptainProps) {
  const t = useTranslations("draftAdmin");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-3 rounded-xl border border-border/70 bg-card px-3 py-2.5",
        isDragging && "relative z-20 border-primary shadow-lg"
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-8 w-8 cursor-grab touch-none active:cursor-grabbing"
        {...attributes}
        {...listeners}
        aria-label={t("moveCaptain", { name: label })}
      >
        <GripVertical className="h-4 w-4" />
      </Button>
      <Badge variant="secondary" className="grid h-7 w-7 place-items-center rounded-full p-0">
        {position}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{label}</span>
      <span className="font-mono text-xs text-muted-foreground">{rank ?? "—"}</span>
    </div>
  );
}

