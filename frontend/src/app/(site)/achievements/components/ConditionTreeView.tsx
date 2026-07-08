"use client";

import { useTranslations } from "next-intl";

import type { ConditionNode } from "@/types/achievement.types";
import { Badge } from "@/components/ui/badge";

type Translator = ReturnType<typeof useTranslations>;

const CONDITION_TYPES = [
  "stat_threshold",
  "match_criteria",
  "match_win",
  "hero_stat",
  "standing_position",
  "standing_record",
  "div_change",
  "div_level",
  "is_captain",
  "is_newcomer",
  "tournament_type",
  "hero_kd_best",
  "team_players_match",
  "captain_property",
  "encounter_score",
  "encounter_revenge",
  "global_stat_sum",
  "tournament_count",
  "global_winrate",
  "distinct_count",
  "consecutive",
  "stable_streak",
] as const;

type ConditionType = (typeof CONDITION_TYPES)[number];
const CONDITION_TYPE_SET = new Set<string>(CONDITION_TYPES);

function isConditionType(value: string): value is ConditionType {
  return CONDITION_TYPE_SET.has(value);
}

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

function formatParamValue(key: string, value: unknown, t: Translator): string {
  if (key === "op" && typeof value === "string") {
    return OP_LABELS[value] ?? value;
  }
  if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value.replace(/_/g, " ");
  if (Array.isArray(value)) return value.join(", ");
  return JSON.stringify(value);
}

function LeafNode({ node }: { node: { type: string; params?: Record<string, unknown> } }) {
  const t = useTranslations();
  const label = isConditionType(node.type)
    ? t(`achievements.condition.${node.type}`)
    : node.type;
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
          <span className="text-white/70">{formatParamValue(key, value, t)}</span>
        </span>
      ))}
    </div>
  );
}

function ConditionTreeNode({ node, depth = 0 }: { node: ConditionNode; depth?: number }) {
  const t = useTranslations();

  if ("AND" in node) {
    return (
      <div className={depth > 0 ? "ml-4 border-l border-blue-500/20 pl-3" : ""}>
        <Badge variant="outline" className="mb-1.5 border-blue-500/30 bg-blue-500/10 text-blue-400 text-xs">
          {t("achievements.logic.and")}
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
          {t("achievements.logic.or")}
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
          {t("achievements.logic.not")}
        </Badge>
        <ConditionTreeNode node={node.NOT} depth={depth + 1} />
      </div>
    );
  }

  if ("type" in node) {
    return <LeafNode node={node as { type: string; params?: Record<string, unknown> }} />;
  }

  return <span className="text-xs text-white/30">{t("achievements.emptyCondition")}</span>;
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
