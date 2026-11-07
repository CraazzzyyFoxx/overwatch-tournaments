"use client";

import { useState } from "react";
import { ChevronDown, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { CanvasPanel, useFocusNode } from "@/components/graph-canvas/GraphCanvas";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { floatingPanelClass } from "@/components/ui/popover";
import { RowButton } from "@/components/ui/row-button";
import { TONE_TEXT } from "@/components/ui/tone";
import type { FlowDraft, KeyedValidation } from "@/lib/flow/flowDraft";
import { cn } from "@/lib/utils";
import type { FlowIssueRead } from "@/types/flow.types";

/** The codes with a message of their own; any other issue shows the server's text. */
const CODES = [
  "invalid_config",
  "invalid_node_config",
  "stage_without_stage_id",
  "unknown_node",
  "unknown_port",
  "port_taken",
  "cycle",
  "unit_mismatch",
  "aggregate_n_exceeds_inputs",
  "team_intake_target",
  "aggregate_by_role_target",
  "missing_input",
  "sink_not_terminal",
  "node_frozen",
  "node_has_dependents",
  "stage_node_managed_by_stage",
  "draft_session_active",
  "changed_on_server"
] as const;
type Code = (typeof CODES)[number];
const isKnown = (code: string): code is Code => (CODES as readonly string[]).includes(code);

/** An issue with the node it is about (the target of an edge's issue) and the edge, when it names one. */
type Entry = { issue: FlowIssueRead; nodeKey: string | null; edgeKey: string | null };

const ROW = "flex items-start gap-2 px-3 py-2 text-caption";

/**
 * The dry run's issues as a panel over the canvas' top-right corner, errors first. Folded it is one line of counts; a new
 * error unfolds it. A row naming a node selects it and brings it into view.
 */
export function FlowIssues({
  keyed,
  draft,
  onSelect
}: Readonly<{ keyed: KeyedValidation; draft: FlowDraft; onSelect: (key: string) => void }>) {
  const t = useTranslations("adminTournament.flow.issues");
  const focus = useFocusNode();
  const entries: Entry[] = [
    ...[...keyed.nodeIssues].flatMap(([key, list]) => list.map((issue) => ({ issue, nodeKey: key, edgeKey: null }))),
    ...[...keyed.edgeIssues].flatMap(([key, list]) =>
      list.map((issue) => ({ issue, nodeKey: draft.edges.find((e) => e.key === key)?.target ?? null, edgeKey: key }))
    ),
    ...keyed.general.map((issue) => ({ issue, nodeKey: null, edgeKey: null })),
    ...draft.nodes
      .filter((n) => n.serverChanged)
      .map((n) => ({
        issue: { code: "changed_on_server", severity: "warning", message: "", node_id: null, edge_id: null } as FlowIssueRead,
        nodeKey: n.key,
        edgeKey: null
      }))
  ].sort((a, b) => Number(b.issue.severity === "error") - Number(a.issue.severity === "error"));
  const errors = entries.filter((e) => e.issue.severity === "error").length;
  const warnings = entries.length - errors;

  const [open, setOpen] = useState(errors > 0);
  const [seenErrors, setSeenErrors] = useState(errors);
  if (errors !== seenErrors) {
    setSeenErrors(errors);
    if (errors > seenErrors) setOpen(true);
  }

  if (entries.length === 0) {
    return (
      <CanvasPanel position="top-right">
        <p role="status" className={cn(floatingPanelClass, "flex items-center gap-2 px-3 py-2 text-caption")}>
          <CircleCheck aria-hidden className={cn("size-4 shrink-0", TONE_TEXT.success)} />
          {t("none")}
        </p>
      </CanvasPanel>
    );
  }

  const unitOf = (key: string, direction: "in" | "out", port: string) =>
    keyed.ports.get(key)?.find((p) => p.direction === direction && p.name === port)?.unit ?? "other";
  const describe = ({ issue, nodeKey, edgeKey }: Entry) => {
    if (!isKnown(issue.code)) return { text: issue.message, detail: null };
    const node = draft.nodes.find((n) => n.key === nodeKey);
    const edge = draft.edges.find((e) => e.key === edgeKey);
    const text = t(`codes.${issue.code}`, {
      kind: node?.kind ?? "other",
      source: edge ? unitOf(edge.source, "out", edge.sourcePort) : "other",
      target: edge ? unitOf(edge.target, "in", edge.targetPort) : "other",
      n: Number(node?.config.n ?? 0),
      inputs: draft.edges.filter((e) => e.target === nodeKey).length
    });
    // Config issues end in the validator's own reason (`<field>: <why>`); it stays, under the translated lead.
    const detail =
      issue.code === "invalid_config"
        ? issue.message.split(": ").slice(1).join(": ")
        : issue.code === "invalid_node_config"
          ? issue.message
          : "";
    return { text, detail: detail || null };
  };

  const tone = errors > 0 ? "danger" : "warning";
  const HeaderIcon = errors > 0 ? CircleX : TriangleAlert;
  const counts = [errors > 0 ? t("errors", { count: errors }) : null, warnings > 0 ? t("warnings", { count: warnings }) : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <CanvasPanel position="top-right" className={open ? "w-80 max-w-[calc(100%-30px)]" : undefined}>
      <Collapsible open={open} onOpenChange={setOpen} className={cn(floatingPanelClass, "overflow-hidden")}>
        <CollapsibleTrigger asChild>
          <RowButton className="group/trigger flex items-center gap-2 px-3 py-2 text-caption">
            <HeaderIcon aria-hidden className={cn("size-4 shrink-0", TONE_TEXT[tone])} />
            <span className="font-semibold">{t("title")}</span>
            <span className="truncate text-muted-foreground">{counts}</span>
            <ChevronDown aria-hidden className={cn(triggerChevronClass, "ml-auto")} />
          </RowButton>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ul className="nowheel max-h-72 divide-y divide-[color:var(--aqt-border)] overflow-y-auto border-t border-[color:var(--aqt-border)]">
            {entries.map((entry, index) => {
              const isError = entry.issue.severity === "error";
              const Icon = isError ? CircleX : TriangleAlert;
              const name = draft.nodes.find((n) => n.key === entry.nodeKey)?.name;
              const { text, detail } = describe(entry);
              const body = (
                <>
                  <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", TONE_TEXT[isError ? "danger" : "warning"])} />
                  <span className="min-w-0">
                    <span className="sr-only">{t(isError ? "error" : "warning")}: </span>
                    {name ? <span className="block truncate font-medium">{name}</span> : null}
                    <span className="block text-muted-foreground">{text}</span>
                    {detail ? <span className="block break-words text-[color:var(--aqt-fg-dim)]">{detail}</span> : null}
                  </span>
                </>
              );
              const key = entry.nodeKey;
              return (
                <li key={index}>
                  {key !== null && name !== undefined ? (
                    <RowButton
                      className={ROW}
                      onClick={() => {
                        onSelect(key);
                        focus(key);
                      }}
                    >
                      {body}
                    </RowButton>
                  ) : (
                    <div className={ROW}>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </CollapsibleContent>
      </Collapsible>
    </CanvasPanel>
  );
}
