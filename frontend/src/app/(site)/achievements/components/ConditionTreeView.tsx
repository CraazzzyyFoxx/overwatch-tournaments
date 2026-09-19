"use client";

import { useTranslations } from "next-intl";

import type { ConditionNode } from "@/types/achievement.types";
import { Badge } from "@/components/ui/badge";

type Translator = ReturnType<typeof useTranslations<never>>;

/**
 * Node labels come from the message catalogue, keyed by the engine's own node
 * name. The component used to keep a hard-coded list of the types it knew; a
 * node the engine added and nobody mirrored here rendered as a raw slug, so the
 * lookup is now "is there a message for it", with a humanized fallback.
 */
function conditionLabel(type: string, t: Translator): string {
  // The key is built from an engine-supplied node name, so it cannot be one of
  // next-intl's statically known literals.
  const key = `achievements.condition.${type}` as Parameters<Translator>[0];
  if (t.has(key)) return t(key);
  const spaced = type.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
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

function LeafNode({ node }: Readonly<{ node: { type: string; params?: Record<string, unknown> } }>) {
  const t = useTranslations();
  const label = conditionLabel(node.type, t);
  const params = node.params ?? {};
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge
        variant="outline"
        className="border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-xs text-[color:var(--aqt-emerald)]"
      >
        {label}
      </Badge>
      {entries.map(([key, value]) => (
        <span key={key} className="text-xs text-[color:var(--aqt-fg-dim)]">
          <span className="text-[color:var(--aqt-fg-faint)]">{key.replace(/_/g, " ")}</span>{" "}
          <span className="text-[color:var(--aqt-fg-muted)]">{formatParamValue(key, value, t)}</span>
        </span>
      ))}
    </div>
  );
}

function ConditionTreeNode({ node, depth = 0 }: Readonly<{ node: ConditionNode; depth?: number }>) {
  const t = useTranslations();

  if ("AND" in node) {
    return (
      <div className={depth > 0 ? "ml-4 border-l border-[color:color-mix(in_srgb,var(--aqt-blue)_20%,transparent)] pl-3" : ""}>
        <Badge
          variant="outline"
          className="mb-1.5 border-[color:color-mix(in_srgb,var(--aqt-blue)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_10%,transparent)] text-xs text-[color:var(--aqt-blue)]"
        >
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
      <div className={depth > 0 ? "ml-4 border-l border-[color:color-mix(in_srgb,var(--aqt-amber)_20%,transparent)] pl-3" : ""}>
        <Badge
          variant="outline"
          className="mb-1.5 border-[color:color-mix(in_srgb,var(--aqt-amber)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-xs text-[color:var(--aqt-amber)]"
        >
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
      <div className={depth > 0 ? "ml-4 border-l border-[color:color-mix(in_srgb,var(--aqt-rose)_20%,transparent)] pl-3" : ""}>
        <Badge
          variant="outline"
          className="mb-1.5 border-[color:color-mix(in_srgb,var(--aqt-rose)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)] text-xs text-[color:var(--aqt-rose)]"
        >
          {t("achievements.logic.not")}
        </Badge>
        <ConditionTreeNode node={node.NOT} depth={depth + 1} />
      </div>
    );
  }

  if ("type" in node) {
    return <LeafNode node={node as { type: string; params?: Record<string, unknown> }} />;
  }

  return (
    <span className="text-xs text-[color:var(--aqt-fg-faint)]">
      {t("achievements.emptyCondition")}
    </span>
  );
}

interface ConditionTreeViewProps {
  tree: ConditionNode;
}

export default function ConditionTreeView({ tree }: Readonly<ConditionTreeViewProps>) {
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <ConditionTreeNode node={tree} />
    </div>
  );
}
