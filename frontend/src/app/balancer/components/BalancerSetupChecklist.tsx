import { CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type WorkflowStepStatus = "done" | "active" | "pending";

type WorkflowAction = {
  label: string;
  onClick: () => void;
  variant?: "primary";
  disabled?: boolean;
};

type WorkflowStepProps = {
  step: number;
  label: string;
  status: WorkflowStepStatus;
  detail: string;
  isLast?: boolean;
  action?: WorkflowAction;
};

type BalancerSetupChecklistProps = {
  poolPlayerCount: number;
  invalidPlayerCount: number;
  canRunBalance: boolean;
  isRunPending: boolean;
  onBrowseAvailable: () => void;
  onReviewConflicts: () => void;
  onRunBalance: () => void;
};

function WorkflowStep({
  step,
  label,
  status,
  detail,
  isLast,
  action,
}: WorkflowStepProps) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ring-4",
            status === "done"
              ? "bg-emerald-500/20 text-emerald-300 ring-emerald-500/8"
              : status === "active"
                ? "bg-primary/25 text-primary ring-primary/10"
                : "bg-white/5 text-[color:var(--aqt-fg-faint)] ring-[color:var(--aqt-border-2)]",
          )}
        >
          {status === "done" ? <CheckCircle2 className="h-4.5 w-4.5" /> : step}
        </div>
        {!isLast ? (
          <div
            className={cn(
              "mt-2 w-px flex-1",
              status === "done" ? "bg-emerald-500/20" : "bg-white/8",
            )}
          />
        ) : null}
      </div>

      <div className={cn("pb-8", isLast && "pb-0")}>
        <div
          className={cn(
            "mt-1.5 text-sm font-semibold leading-none",
            status === "pending" ? "text-[color:var(--aqt-fg-faint)]" : "text-[color:var(--aqt-fg)]",
          )}
        >
          {label}
        </div>
        <div
          className={cn(
            "mt-1.5 text-xs",
            status === "pending" ? "text-[color:var(--aqt-fg-faint)]" : "text-[color:var(--aqt-fg-dim)]",
          )}
        >
          {detail}
        </div>
        {action && status === "active" ? (
          <Button
            size="sm"
            onClick={action.onClick}
            disabled={action.disabled}
            className={cn(
              "mt-3 rounded-lg",
              action.variant === "primary"
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "border border-[color:var(--aqt-border-2)] bg-black/15 text-[color:var(--aqt-fg-muted)] hover:bg-white/5 hover:text-[color:var(--aqt-fg)]",
            )}
          >
            {action.label}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function BalancerSetupChecklist({
  poolPlayerCount,
  invalidPlayerCount,
  canRunBalance,
  isRunPending,
  onBrowseAvailable,
  onReviewConflicts,
  onRunBalance,
}: BalancerSetupChecklistProps) {
  const hasPoolPlayers = poolPlayerCount > 0;
  const hasInvalidPlayers = invalidPlayerCount > 0;

  return (
    <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-[color:var(--aqt-border-2)] bg-white/2">
      <div className="w-full max-w-sm px-6">
        <WorkflowStep
          step={1}
          label="Add players to pool"
          status={hasPoolPlayers ? "done" : "active"}
          detail={
            hasPoolPlayers
              ? `${poolPlayerCount} player${poolPlayerCount !== 1 ? "s" : ""} included`
              : "Use search to bring approved registrations into the pool"
          }
          action={
            !hasPoolPlayers
              ? { label: "Browse available", onClick: onBrowseAvailable }
              : undefined
          }
        />
        <WorkflowStep
          step={2}
          label="Resolve issues"
          status={!hasPoolPlayers ? "pending" : hasInvalidPlayers ? "active" : "done"}
          detail={
            hasInvalidPlayers
              ? `${invalidPlayerCount} player${invalidPlayerCount !== 1 ? "s" : ""} need fixes`
              : "All players are ready"
          }
          action={
            hasInvalidPlayers
              ? { label: "Review conflicts", onClick: onReviewConflicts }
              : undefined
          }
        />
        <WorkflowStep
          step={3}
          label="Run the balancer"
          isLast
          status={canRunBalance ? "active" : "pending"}
          detail="Pick a preset above and generate team compositions"
          action={
            canRunBalance
              ? {
                  label: "Run balance",
                  onClick: onRunBalance,
                  variant: "primary",
                  disabled: isRunPending,
                }
              : undefined
          }
        />
      </div>
    </div>
  );
}
