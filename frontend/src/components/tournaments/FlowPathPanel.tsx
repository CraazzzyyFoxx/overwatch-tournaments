"use client";

import { Fragment, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { useFlowPath } from "@/hooks/useFlowPath";
import { getApiErrorMessage } from "@/lib/api/error";
import { firstLifecycleSuccessor, lifecycleAncestors, stepsTo, type FlowStep } from "@/lib/tournament/flow-path";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, Tone> = {
  open: "success",
  check_in: "info",
  forming: "info",
  ready: "info",
  live: "success",
  completed: "success"
};

/**
 * Where the tournament is on its way to `focusNodeId`, and the one thing to do next. A formation screen
 * (`focus` a formation) shows the registrations feeding it, the formation and the stage it feeds; a bracket screen
 * (`focus` a stage) shows the chain up to that stage. The next move is planned by `stepsTo`, so it is the same order the
 * server enforces; every move it lists is one confirmation away.
 *
 * A formation that is `forming` waits for its teams: `teamsExported` tells it the export happened, and until then the
 * panel says so instead of offering to complete the formation (the server would refuse an empty one).
 */
export function FlowPathPanel({
  tournamentId,
  focusNodeId,
  canUpdate,
  teamsExported = true
}: Readonly<{ tournamentId: number; focusNodeId: number; canUpdate: boolean; teamsExported?: boolean }>) {
  const t = useTranslations("common.flowPath");
  const flowMessage = useFlowErrorMessage();
  const { graph, stepLabel, statusLabel, run } = useFlowPath(tournamentId);
  const [asking, setAsking] = useState<FlowStep[] | null>(null);
  const [running, setRunning] = useState(false);

  const focus = graph?.nodes.find((node) => node.id === focusNodeId);
  if (!graph || !focus) return null;

  const successor = focus.kind === "formation" ? firstLifecycleSuccessor(graph, focus.id) : null;
  const chain = [...lifecycleAncestors(graph, focus.id), focus, ...(successor ? [successor] : [])];

  // What the screen is for: a formation first forms (and, once its teams are in, completes into its stage); a stage goes live.
  let plan: FlowStep[] | null = [];
  let waitingForExport = false;
  if (focus.kind === "stage") {
    plan = ["live", "completed"].includes(focus.status) ? [] : stepsTo(graph, focus.id, "live");
  } else if (focus.status !== "forming" && focus.status !== "completed") {
    plan = stepsTo(graph, focus.id, "forming");
  } else if (focus.status === "forming" && !teamsExported) {
    waitingForExport = true;
  } else if (successor && !["live", "completed"].includes(successor.status)) {
    plan = stepsTo(graph, successor.id, "live");
  }

  // Two moves are not the organizer's to press: a live stage completes from its standings, and a formation completes
  // only once teams are exported into it. The list stops there and says what it waits for.
  const waitsOnStage = plan?.findIndex((step) => step.node.kind === "stage" && step.from === "live") ?? -1;
  const waitsOnExport = plan?.findIndex((step) => step.node.kind === "formation" && step.to === "forming") ?? -1;
  const stopAt = Math.min(
    waitsOnStage === -1 ? Infinity : waitsOnStage,
    waitsOnExport === -1 ? Infinity : waitsOnExport + 1
  );
  const shown = plan && Number.isFinite(stopAt) ? plan.slice(0, stopAt) : plan;
  const then =
    stopAt === waitsOnStage
      ? t("waitStage", { name: (plan as FlowStep[])[waitsOnStage].node.name })
      : Number.isFinite(stopAt)
        ? t("exportTeams")
        : null;

  const confirm = async (steps: FlowStep[]) => {
    setRunning(true);
    try {
      await run(steps);
    } catch (error) {
      notify.error(flowMessage(error) ?? getApiErrorMessage(error, t("blocked")));
    } finally {
      setRunning(false);
      setAsking(null);
    }
  };

  return (
    <section aria-label={t("title")} className="space-y-2 rounded-xl border border-[color:var(--aqt-border)] p-3">
      <ol className="flex flex-wrap items-center gap-1.5">
        {chain.map((node, index) => (
          <Fragment key={node.id}>
            {index > 0 ? <ChevronRight aria-hidden className="h-3.5 w-3.5 text-[color:var(--aqt-fg-faint)]" /> : null}
            <li className={cn("flex items-center gap-1.5", node.id === focus.id && "font-semibold")}>
              <span className="text-caption">{node.name}</span>
              <StatusPill tone={STATUS_TONE[node.status] ?? "neutral"}>{statusLabel(node)}</StatusPill>
            </li>
          </Fragment>
        ))}
      </ol>

      {waitingForExport ? (
        <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("exportTeams")}</p>
      ) : shown === null ? (
        <p className="text-caption text-warning">{t("blocked")}</p>
      ) : shown.length === 0 ? (
        <p className="text-caption text-[color:var(--aqt-fg-dim)]">{then ?? t("done")}</p>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-1">
            <ol className="list-decimal space-y-0.5 pl-5 text-caption">
              {shown.map((step) => (
                <li key={`${step.node.id}-${step.to}`}>{stepLabel(step)}</li>
              ))}
            </ol>
            {then ? <p className="text-caption text-[color:var(--aqt-fg-dim)]">{then}</p> : null}
          </div>
          {canUpdate ? (
            <Button size="sm" disabled={running} onClick={() => setAsking(shown.slice(0, 1))}>
              {t("next")}: {stepLabel(shown[0])}
            </Button>
          ) : null}
        </div>
      )}

      {asking ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setAsking(null)}
          intent={{
            title: `${stepLabel(asking[0])}?`,
            description: t(`consequence.${asking[0].node.kind}.${asking[0].to}` as never),
            confirmLabel: t("run"),
            tone: asking[0].to === "closed" || asking[0].to === "completed" ? "warning" : "neutral"
          }}
          pending={running}
          onConfirm={() => confirm(asking)}
        />
      ) : null}
    </section>
  );
}
