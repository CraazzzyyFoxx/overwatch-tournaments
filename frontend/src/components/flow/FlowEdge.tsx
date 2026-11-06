"use client";

import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/** xyflow's default bezier edge, plus a remove button at its midpoint while selected. */
export function FlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  interactionWidth,
  selected,
  deletable
}: EdgeProps) {
  const t = useTranslations("common.flow");
  const { deleteElements } = useReactFlow();
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} interactionWidth={interactionWidth} />
      {selected && deletable !== false ? (
        <EdgeLabelRenderer>
          <Button
            type="button"
            variant="destructive"
            size="icon-xs"
            aria-label={t("deleteEdge")}
            title={t("deleteEdge")}
            className="nodrag nopan pointer-events-auto absolute rounded-full"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
            onClick={() => void deleteElements({ edges: [{ id }] })}
          >
            <X aria-hidden />
          </Button>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
