"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { useFlowPath } from "@/hooks/useFlowPath";
import { getApiErrorMessage } from "@/lib/api/error";
import type { StageProgress } from "@/lib/bracket/projection";
import type { FlowStep, PathNode } from "@/lib/tournament/flow-path";
import { notify } from "@/lib/notify";
import type { Stage } from "@/types/tournament.types";

/**
 * What stands upstream of a stage going live, from `plan` (`stepsTo(stage → live)`, inputs first). Renders nothing
 * when the plan starts with the stage's own move: the header's button takes it from there.
 *
 * The list stops at the first move that is not the organizer's to press: a live stage completes from its standings,
 * and a formation completes only once teams are exported into it. One line then says what it waits for.
 */
export function StageNextStep({
  stage,
  plan,
  stages,
  progressByStageId,
  canUpdate
}: Readonly<{
  stage: Stage;
  plan: FlowStep[] | null;
  stages: Stage[];
  progressByStageId: ReadonlyMap<number, StageProgress>;
  canUpdate: boolean;
}>) {
  const t = useTranslations("common.flowPath");
  const flowMessage = useFlowErrorMessage();
  const { stepLabel, run } = useFlowPath(stage.tournament_id);
  const [asking, setAsking] = useState<FlowStep | null>(null);
  const [running, setRunning] = useState(false);

  if (plan === null) return <Warning>{t("blocked")}</Warning>;
  if (plan.length === 0 || plan[0].node.id === stage.node_id) return null;

  const waitsOnStage = plan.findIndex((step) => step.node.kind === "stage" && step.from === "live");
  const waitsOnExport = plan.findIndex((step) => step.node.kind === "formation" && step.to === "forming");
  const stopAt = Math.min(
    waitsOnStage === -1 ? plan.length : waitsOnStage,
    waitsOnExport === -1 ? plan.length : waitsOnExport + 1
  );
  const shown = plan.slice(0, stopAt);

  const waitFor = (node: PathNode) => {
    const upstream = stages.find((candidate) => candidate.node_id === node.id);
    const progress = upstream ? progressByStageId.get(upstream.id) : undefined;
    if (!progress || progress.total === 0) return t("waitStage", { name: node.name });
    const left = progress.total - progress.completed;
    if (left > 0) return t("waitStageMatches", { name: node.name, count: left });
    // The counts cover only matches that exist: a Swiss stage may still have rounds to pair. An individual Swiss
    // completes only by its qualification lock.
    return upstream?.stage_type === "individual_swiss"
      ? t("waitStageLock", { name: node.name })
      : t("waitStagePlayed", { name: node.name });
  };
  const then = stopAt === waitsOnStage ? waitFor(plan[waitsOnStage].node) : stopAt < plan.length ? t("exportTeams") : null;

  // Nothing to press before the wait: the one line is the whole story.
  if (shown.length === 0) return <Warning>{then}</Warning>;

  const confirm = async (step: FlowStep) => {
    setRunning(true);
    try {
      await run([step]);
    } catch (error) {
      notify.error(flowMessage(error) ?? getApiErrorMessage(error, t("blocked")));
    } finally {
      setRunning(false);
      setAsking(null);
    }
  };

  return (
    <section
      aria-label={t("planTitle", { name: stage.name })}
      className="mt-3 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-warning/40 p-3"
    >
      <div className="space-y-1.5">
        <p className="text-caption font-semibold">{t("planTitle", { name: stage.name })}</p>
        <ol className="list-decimal space-y-0.5 pl-5 text-caption">
          {shown.map((step, index) => (
            <li key={`${step.node.id}-${step.to}`} className={index > 0 ? "text-[color:var(--aqt-fg-dim)]" : undefined}>
              {stepLabel(step)}
            </li>
          ))}
        </ol>
        {then ? <p className="text-caption text-[color:var(--aqt-fg-dim)]">{then}</p> : null}
      </div>
      {canUpdate ? (
        <Button size="sm" disabled={running} onClick={() => setAsking(shown[0])}>
          {t("doFirst")}
        </Button>
      ) : null}

      {asking ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setAsking(null)}
          intent={{
            title: `${stepLabel(asking)}?`,
            description: t(`consequence.${asking.node.kind}.${asking.to}` as never),
            confirmLabel: t("run"),
            tone: asking.to === "closed" || asking.to === "completed" ? "warning" : "neutral"
          }}
          pending={running}
          onConfirm={() => confirm(asking)}
        />
      ) : null}
    </section>
  );
}

function Warning({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <p className="mt-2 flex items-center gap-1.5 text-caption text-warning">
      <AlertTriangle aria-hidden className="size-3.5 shrink-0" />
      {children}
    </p>
  );
}
