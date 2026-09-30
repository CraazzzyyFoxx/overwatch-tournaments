"use client";

import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, LockKeyhole, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useDragSensors } from "@/hooks/useDragSensors";
import type { RosterShape } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftCaptainOrder, DraftFormat } from "@/types/draft.types";

import { orderCaptainIds, reseatCaptain } from "./setup-model";
import { DraftSetupPreview } from "./DraftSetupPreview";
import type { DraftCaptainSetup } from "./setup-types";
import { captainSeat, registrationLabel } from "./setup-types";

interface DraftOrderStepProps {
  value: DraftCaptainSetup;
  onChange: (next: DraftCaptainSetup) => void;
  pool: AdminRegistration[];
  rounds: number;
  format: DraftFormat;
  roundRules: string[];
  rosterShape: Pick<RosterShape, "slots" | "has_role_slots">;
}

export function DraftOrderStep({
  value,
  onChange,
  pool,
  rounds,
  format,
  roundRules,
  rosterShape
}: Readonly<DraftOrderStepProps>) {
  const t = useTranslations("draftAdmin");
  // No activation distance: a captain row carries no controls of its own, so
  // there is no click here for a threshold to protect.
  const sensors = useDragSensors({ distance: 0, keyboard: true });
  // Same rank the captain step shows and the server seats by: the rank of the
  // role each captain is seated on.
  const ranks = new Map(
    pool.map((registration) => [
      registration.id,
      captainSeat(registration, value.roles[registration.id], rosterShape).rank
    ])
  );
  const orderedIds = orderCaptainIds(value.ids, value.order, ranks, value.randomSeed);

  // Every order is draggable: a drag overrides the seeds of a computed order
  // by turning it into the manual one it was showing (`reseatCaptain`).
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    onChange(reseatCaptain(value, orderedIds, Number(active.id), Number(over.id)));
  };

  return (
    <div className="@container">
      <div className="grid gap-6 @3xl:grid-cols-2 @3xl:items-start">
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="captain-order">{t("captainOrder")}</Label>
            <div className="flex items-center gap-2">
              <Select
                value={value.order}
                onValueChange={(order) => onChange({ ...value, order: order as DraftCaptainOrder })}
              >
                <SelectTrigger
                  id="captain-order"
                  className="min-w-0 flex-1"
                  aria-label={t("captainOrder")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="weakest_first">{t("orders.weakest_first.title")}</SelectItem>
                  <SelectItem value="strongest_first">
                    {t("orders.strongest_first.title")}
                  </SelectItem>
                  <SelectItem value="random">{t("orders.random.title")}</SelectItem>
                  <SelectItem value="manual">{t("orders.manual.title")}</SelectItem>
                </SelectContent>
              </Select>
              {value.order === "random" && (
                <div className="flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-border/70 bg-muted/20 pl-2.5 pr-1">
                  <LockKeyhole className="h-4 w-4 text-muted-foreground" aria-hidden />
                  <span className="font-mono text-xs tabular-nums">{value.randomSeed}</span>
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
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </div>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              {t(`orders.${value.order}.description`)}
            </p>
            {value.order !== "manual" && (
              <p className="text-xs text-muted-foreground">{t("dragToOverrideSeeds")}</p>
            )}
          </div>

          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={orderedIds} strategy={verticalListSortingStrategy}>
              <div className="space-y-2">
                {orderedIds.map((id, index) => {
                  const registration = pool.find((candidate) => candidate.id === id);
                  if (!registration) return null;
                  return (
                    <SortableCaptain
                      key={id}
                      id={id}
                      position={index + 1}
                      label={registrationLabel(registration)}
                      rank={ranks.get(id) ?? null}
                    />
                  );
                })}
              </div>
            </SortableContext>
          </DndContext>
        </div>

        <DraftSetupPreview
          orderedCaptainIds={orderedIds}
          pool={pool}
          rounds={rounds}
          format={format}
          roundRules={roundRules}
        />
      </div>
    </div>
  );
}

interface SortableCaptainProps {
  id: number;
  position: number;
  label: string;
  rank: number | null;
}

function SortableCaptain({ id, position, label, rank }: Readonly<SortableCaptainProps>) {
  const t = useTranslations("draftAdmin");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id
  });
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
        <GripVertical className="h-4 w-4" aria-hidden />
      </Button>
      <Badge
        variant="secondary"
        className="grid h-7 w-7 place-items-center rounded-full p-0 tabular-nums"
      >
        {position}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{label}</span>
      <span className="font-mono text-xs tabular-nums text-muted-foreground">{rank ?? "—"}</span>
    </div>
  );
}
