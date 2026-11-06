"use client";

import { GripVertical } from "lucide-react";
import { useTranslations } from "next-intl";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { RowButton } from "@/components/ui/row-button";
import { FLOW_NODE_MIME } from "@/lib/flow/flowCanvas";
import { LIFECYCLE_KINDS, PURE_KINDS } from "@/lib/flow/kinds";
import type { FlowNodeKind } from "@/types/flow.types";

const GROUPS = [
  { key: "lifecycle", kinds: LIFECYCLE_KINDS },
  { key: "transitions", kinds: PURE_KINDS }
] as const;

/** The node kinds to add: drag one onto the canvas, or click it (a drag is the one gesture a keyboard cannot make). */
export function FlowPalette({ onAdd }: Readonly<{ onAdd: (kind: FlowNodeKind) => void }>) {
  const t = useTranslations("adminTournament.flow.palette");
  const tKind = useTranslations("common.flow.kind");

  return (
    <div className="space-y-3 text-caption">
      <p className={eyebrowClass("muted")}>{t("title")}</p>
      <p className="text-muted-foreground">{t("hint")}</p>
      {GROUPS.map((group) => (
        <div key={group.key}>
          <p className={`${eyebrowClass("muted")} mb-1`}>{t(group.key)}</p>
          {group.kinds.map((kind) => (
            <RowButton
              key={kind}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(FLOW_NODE_MIME, kind);
                e.dataTransfer.effectAllowed = "move";
              }}
              onClick={() => onAdd(kind)}
              aria-label={t("add", { kind: tKind(kind) })}
              className="flex cursor-grab items-center gap-1.5 rounded px-2 py-1 active:cursor-grabbing"
            >
              <GripVertical className="size-3 text-muted-foreground" aria-hidden />
              <span className="truncate">{tKind(kind)}</span>
            </RowButton>
          ))}
        </div>
      ))}
    </div>
  );
}
