"use client";

import { useTranslations } from "next-intl";

import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

interface FlowNodeSelectProps {
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined;
  kind: "registration" | "formation";
  value: number | null;
  onChange: (nodeId: number) => void;
}

/** Picks which registration or formation node a screen works on; a tournament with one node needs no picker. */
export function FlowNodeSelect({ tournament, kind, value, onChange }: Readonly<FlowNodeSelectProps>) {
  const t = useTranslations("admin.flowNodeSelect");
  const nodes = nodesOfKind(tournament, kind);
  if (nodes.length < 2) return null;
  const label = t("label", { kind });
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={`flow-node-${kind}`}>{label}</Label>
      <Select value={value == null ? undefined : String(value)} onValueChange={(next) => onChange(Number(next))}>
        <SelectTrigger id={`flow-node-${kind}`} aria-label={label} size="sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {nodes.map((node) => (
            <SelectItem key={node.id} value={String(node.id)}>
              {node.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
