"use client";

import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow, type EdgeProps } from "@xyflow/react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";

/**
 * The one edge every canvas draws: a 2px bezier in the colour its `style.stroke` names, rose and moving while
 * `data.invalid`, and a remove button at its midpoint while selected and deletable. Selection thickens the stroke,
 * since an inline stroke colour outranks xyflow's selected colour.
 */
export function GraphEdge({
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
  deletable,
  data
}: EdgeProps) {
  const t = useTranslations("common.graphCanvas");
  const { deleteElements } = useReactFlow();
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const invalid = data?.invalid === true;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        interactionWidth={interactionWidth}
        // `dashdraw` is xyflow's own keyframe for `animated` edges, which ignore reduced motion.
        className={invalid ? "[stroke-dasharray:5] motion-safe:animate-[dashdraw_0.5s_linear_infinite]" : undefined}
        style={{ ...style, strokeWidth: selected ? 3 : 2, ...(invalid ? { stroke: "var(--aqt-rose)" } : null) }}
      />
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
