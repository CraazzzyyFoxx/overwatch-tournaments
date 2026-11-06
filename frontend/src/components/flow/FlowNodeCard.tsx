"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { HANDLE_COLOR, type FlowNodeData } from "@/lib/flow/flowCanvas";
import { UNIT_COLOR } from "@/lib/flow/kinds";
import type { FlowUnit } from "@/types/flow.types";

/** One flow node: kind, name, status and issue badges, and a typed handle per resolved port. */
export function FlowNodeCard({ data }: NodeProps<Node<FlowNodeData>>) {
  const t = useTranslations("common.flow");
  const kind = t(`kind.${data.kind}`);
  const status = data.status ? t(`status.${data.status}`) : null;

  return (
    <div
      aria-label={[data.name, kind, status].filter(Boolean).join(", ")}
      className="min-w-44 rounded-lg border-2 bg-card px-3 py-2 shadow-md"
    >
      <div className="text-label text-muted-foreground">{kind}</div>
      <div className="max-w-56 truncate text-caption font-semibold">{data.name}</div>
      <div className="mt-1 flex flex-wrap gap-1">
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
      {data.ports.map((port, index) => {
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
            style={{
              background: (unit && UNIT_COLOR[unit]) || HANDLE_COLOR,
              top: `${30 + index * 18}%`
            }}
          />
        );
      })}
    </div>
  );
}
