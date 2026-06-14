"use client";

import type { ConditionNode } from "@/types/achievement.types";
import { Badge } from "@/components/ui/badge";

const CONDITION_LABELS: Record<string, string> = {
  stat_threshold: "Stat Threshold",
  match_criteria: "Match Criteria",
  match_win: "Match Win",
  hero_stat: "Hero Stat",
  standing_position: "Standing Position",
  standing_record: "Standing Record",
  div_change: "Division Change",
  div_level: "Division Level",
  is_captain: "Is Captain",
  is_newcomer: "Is Newcomer",
  tournament_type: "Tournament Type",
  hero_kd_best: "Hero K/D Best",
  team_players_match: "Team Players Match",
  captain_property: "Captain Property",
  encounter_score: "Encounter Score",
  encounter_revenge: "Encounter Revenge",
  global_stat_sum: "Global Stat Sum",
  tournament_count: "Tournament Count",
  global_winrate: "Global Winrate",
  distinct_count: "Distinct Count",
  consecutive: "Consecutive",
  stable_streak: "Stable Streak",
};

const OP_LABELS: Record<string, string> = {
  ">=": "\u2265",
  "<=": "\u2264",
  ">": ">",
  "<": "<",
  "==": "=",
  "!=": "\u2260",
  eq: "=",
  ne: "\u2260",
  gt: ">",
  lt: "<",
  gte: "\u2265",
  lte: "\u2264",
};

function formatParamValue(key: string, value: unknown): string {
  if (key === "op" && typeof value === "string") {
    return OP_LABELS[value] ?? value;
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value.replace(/_/g, " ");
  if (Array.isArray(value)) return value.join(", ");
  return JSON.stringify(value);
}

function LeafNode({ node }: { node: { type: string; params?: Record<string, unknown> } }) {
  const label = CONDITION_LABELS[node.type] ?? node.type;
  const params = node.params ?? {};
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs">
        {label}
      </Badge>
      {entries.map(([key, value]) => (
        <span key={key} className="text-xs text-white/50">
          <span className="text-white/30">{key.replace(/_/g, " ")}</span>{" "}
          <span className="text-white/70">{formatParamValue(key, value)}</span>
        </span>
      ))}
    </div>
  );
}

function ConditionTreeNode({ node, depth = 0 }: { node: ConditionNode; depth?: number }) {
  if ("AND" in node) {
    return (
      <div className={depth > 0 ? "ml-4 border-l border-blue-500/20 pl-3" : ""}>
        <Badge variant="outline" className="mb-1.5 border-blue-500/30 bg-blue-500/10 text-blue-400 text-xs">
          AND
        </Badge>
        <div className="flex flex-col gap-1.5">
          {node.AND.map((child, i) => (
            <ConditionTreeNode key={i} node={child} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }

  if ("OR" in node) {
    return (
      <div className={depth > 0 ? "ml-4 border-l border-amber-500/20 pl-3" : ""}>
        <Badge variant="outline" className="mb-1.5 border-amber-500/30 bg-amber-500/10 text-amber-400 text-xs">
          OR
        </Badge>
        <div className="flex flex-col gap-1.5">
          {node.OR.map((child, i) => (
            <ConditionTreeNode key={i} node={child} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }

  if ("NOT" in node) {
    return (
      <div className={depth > 0 ? "ml-4 border-l border-red-500/20 pl-3" : ""}>
        <Badge variant="outline" className="mb-1.5 border-red-500/30 bg-red-500/10 text-red-400 text-xs">
          NOT
        </Badge>
        <ConditionTreeNode node={node.NOT} depth={depth + 1} />
      </div>
    );
  }

  if ("type" in node) {
    return <LeafNode node={node as { type: string; params?: Record<string, unknown> }} />;
  }

  return <span className="text-xs text-white/30">Empty condition</span>;
}

interface ConditionTreeViewProps {
  tree: ConditionNode;
}

export default function ConditionTreeView({ tree }: ConditionTreeViewProps) {
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <ConditionTreeNode node={tree} />
    </div>
  );
}
