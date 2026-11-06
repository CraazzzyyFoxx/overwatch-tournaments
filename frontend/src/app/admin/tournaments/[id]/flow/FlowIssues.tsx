"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { FlowDraft, KeyedValidation } from "@/lib/flow/flowDraft";
import type { FlowIssueRead } from "@/types/flow.types";

type Entry = { issue: FlowIssueRead; key: string | null };

/** The dry run's issues, errors first; one that names a node or edge selects the node it belongs to. */
export function FlowIssues({
  keyed,
  draft,
  onSelect
}: Readonly<{ keyed: KeyedValidation; draft: FlowDraft; onSelect: (key: string) => void }>) {
  const t = useTranslations("adminTournament.flow.issues");
  const edgeNode = (edgeKey: string) => draft.edges.find((e) => e.key === edgeKey)?.target ?? null;
  const entries: Entry[] = [
    ...[...keyed.nodeIssues].flatMap(([key, list]) => list.map((issue) => ({ issue, key }))),
    ...[...keyed.edgeIssues].flatMap(([key, list]) => list.map((issue) => ({ issue, key: edgeNode(key) }))),
    ...keyed.general.map((issue) => ({ issue, key: null }))
  ].sort((a, b) => Number(b.issue.severity === "error") - Number(a.issue.severity === "error"));

  return (
    <section aria-label={t("title")} className="space-y-2">
      <h3 className="text-caption font-semibold">{t("title")}</h3>
      {entries.length === 0 ? <p className="text-caption text-muted-foreground">{t("none")}</p> : null}
      <ul className="space-y-1">
        {entries.map(({ issue, key }, index) => {
          const name = draft.nodes.find((n) => n.key === key)?.name;
          return (
            <li key={index} className="flex flex-wrap items-center gap-2 text-caption">
              <Badge tone={issue.severity === "error" ? "danger" : "warning"} size="sm">
                {t(issue.severity === "error" ? "error" : "warning")}
              </Badge>
              <span>{issue.message}</span>
              {key !== null && name !== undefined ? (
                <Button type="button" variant="link" size="inline" onClick={() => onSelect(key)}>
                  {name}
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
