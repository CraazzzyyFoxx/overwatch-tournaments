"use client";

import { Badge } from "@/components/ui/badge";

interface ConditionTreeGraphProps {
  tree: Record<string, unknown>;
}

export function ConditionTreeGraph({ tree }: ConditionTreeGraphProps) {
  if (!tree || Object.keys(tree).length === 0) {
    return <p className="text-sm text-muted-foreground italic">No conditions defined yet</p>;
  }
  return (
    <div className="font-mono text-sm">
      <TreeNode node={tree} depth={0} isLast />
    </div>
  );
}

function TreeNode({
  node,
  depth,
  isLast,
}: {
  node: Record<string, unknown>;
  depth: number;
  isLast: boolean;
}) {
  const indent = depth > 0;
  const connector = indent ? (isLast ? "\u2514\u2500 " : "\u251C\u2500 ") : "";
  const linePrefix = indent ? (isLast ? "   " : "\u2502  ") : "";

  // AND / OR
  for (const op of ["AND", "OR"] as const) {
    if (op in node) {
      const children = (node[op] as Record<string, unknown>[]) || [];
      return (
        <div>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground whitespace-pre">{connector}</span>
            <Badge
              variant={op === "AND" ? "default" : "secondary"}
              className="text-xs px-1.5 py-0"
            >
              {op}
            </Badge>
          </div>
          {children.map((child, i) => (
            <div key={i} className="ml-5">
              <TreeNode
                node={child}
                depth={depth + 1}
                isLast={i === children.length - 1}
              />
            </div>
          ))}
        </div>
      );
    }
  }

  // NOT
  if ("NOT" in node) {
    const child = node["NOT"] as Record<string, unknown>;
    return (
      <div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground whitespace-pre">{connector}</span>
          <Badge variant="destructive" className="text-xs px-1.5 py-0">
            NOT
          </Badge>
        </div>
        <div className="ml-5">
          <TreeNode node={child} depth={depth + 1} isLast />
        </div>
      </div>
    );
  }

  // Leaf
  const condType = (node.type as string) || "unknown";
  const params = (node.params as Record<string, unknown>) || {};
  const paramStr = formatParams(condType, params);

  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <span className="text-muted-foreground whitespace-pre">{connector}</span>
      <Badge variant="outline" className="text-xs px-1.5 py-0 bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800">
        {condType}
      </Badge>
      {paramStr && (
        <span className="text-xs text-muted-foreground">{paramStr}</span>
      )}
    </div>
  );
}

function formatParams(type: string, params: Record<string, unknown>): string {
  const parts: string[] = [];

  if (params.stat) parts.push(`stat=${params.stat}`);
  if (params.field) parts.push(`field=${params.field}`);
  if (params.op) parts.push(`${params.op} ${params.value ?? ""}`);
  if (params.direction) parts.push(`${params.direction} >= ${params.min_shift}`);
  if (params.hero_slug) parts.push(`hero=${params.hero_slug}`);
  if (params.mode) parts.push(`mode=${params.mode}`);
  if (params.metric) parts.push(`metric=${params.metric}`);
  if (params.min_streak) parts.push(`streak >= ${params.min_streak}`);
  if (params.order) parts.push(`${params.order} top ${params.limit ?? ""}`);
  if (params.is_league !== undefined) parts.push(`league=${params.is_league}`);
  if (params.round_type) parts.push(`round=${params.round_type}`);
  if (params.count_op) parts.push(`count ${params.count_op} ${params.count_value}`);
  if (params.scope && !params.op) parts.push(`scope=${params.scope}`);

  if (["match_win", "is_captain", "is_newcomer", "encounter_revenge"].includes(type)) {
    return "";
  }

  return parts.length > 0 ? `(${parts.join(", ")})` : "";
}
