"use client";

import { Handle, Position, useUpdateNodeInternals, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { GraphNodeCard } from "@/components/graph-canvas/GraphNodeCard";
import { Badge } from "@/components/ui/badge";
import type { FlowNodeData } from "@/lib/flow/flowCanvas";
import { UNIT_COLOR } from "@/lib/flow/kinds";
import type { FlowUnit } from "@/types/flow.types";

/** One flow node: kind, name, status and issue badges, and a typed handle per resolved port. */
export function FlowNodeCard({ id, data, selected }: NodeProps<Node<FlowNodeData>>) {
  const t = useTranslations("common.flow");
  const kind = t(`kind.${data.kind}`);
  const status = data.status ? t(`status.${data.status}`) : null;
  // Ports arrive after the node mounts (dry run, refetch after Save); xyflow only connects handles it has measured. The
  // mount itself is xyflow's to measure: a re-measure then would run the initial fit before the other nodes are measured.
  const updateNodeInternals = useUpdateNodeInternals();
  const handles = data.ports.map((port) => `${port.direction}-${port.name}`).join("|");
  const measuredHandles = useRef(handles);
  useEffect(() => {
    if (measuredHandles.current === handles) return;
    measuredHandles.current = handles;
    updateNodeInternals(id);
  }, [id, handles, updateNodeInternals]);

  const badged = status !== null || data.issueCount > 0 || data.serverChanged;
  return (
    <GraphNodeCard
      aria-label={[data.name, kind, status].filter(Boolean).join(", ")}
      selected={selected}
      className="min-w-44"
      eyebrow={kind}
      title={<span className="block max-w-56 truncate">{data.name}</span>}
      handles={data.ports.map((port, index) => {
        const unit = port.unit as FlowUnit | null;
        const input = port.direction === "in";
        return (
          <Handle
            key={`${port.direction}-${port.name}`}
            id={port.name}
            type={input ? "target" : "source"}
            position={input ? Position.Left : Position.Right}
            isConnectable={!data.readOnly}
            title={unit ? t("port", { port: port.name, unit: t(`unit.${unit}`) }) : port.name}
            style={{ background: unit ? UNIT_COLOR[unit] : undefined, top: `${30 + index * 18}%` }}
          />
        );
      })}
    >
      {badged ? (
        <div className="flex flex-wrap gap-1">
          {status ? (
            <Badge tone="neutral" size="sm">
              {status}
            </Badge>
          ) : null}
          {data.issueCount > 0 ? (
            <Badge tone="danger" size="sm">
              {data.issueCount}
            </Badge>
          ) : null}
          {data.serverChanged ? (
            <Badge tone="warning" size="sm">
              {t("serverChanged")}
            </Badge>
          ) : null}
        </div>
      ) : null}
    </GraphNodeCard>
  );
}

export const flowNodeTypes = { flowNode: FlowNodeCard };
