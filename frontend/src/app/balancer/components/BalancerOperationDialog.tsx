import { AlertTriangle, CheckCircle2, Circle, Loader2, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

export type BalancerOperationStepStatus = "pending" | "running" | "succeeded" | "failed";

export type BalancerOperationStep = {
  id: string;
  label: string;
  description?: string;
  status: BalancerOperationStepStatus;
};

export type BalancerOperationStepDefinition = Omit<BalancerOperationStep, "status">;

type BalancerOperationDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  steps: BalancerOperationStep[];
  isRunning: boolean;
  summary: string | null;
  error: string | null;
  retryLabel?: string;
  onRetry?: () => void;
};

export function createOperationSteps(
  definitions: BalancerOperationStepDefinition[]
): BalancerOperationStep[] {
  return definitions.map((step) => ({ ...step, status: "pending" }));
}

export function updateOperationStepStatus(
  steps: BalancerOperationStep[],
  stepId: string,
  status: BalancerOperationStepStatus
): BalancerOperationStep[] {
  return steps.map((step) => (step.id === stepId ? { ...step, status } : step));
}

function OperationStepIcon({ status }: { status: BalancerOperationStepStatus }) {
  if (status === "running") {
    return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
  }

  if (status === "succeeded") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  }

  if (status === "failed") {
    return <AlertTriangle className="h-4 w-4 text-destructive" />;
  }

  return <Circle className="h-4 w-4 text-muted-foreground/55" />;
}

function getStatusLabel(status: BalancerOperationStepStatus): string {
  if (status === "running") return "Running";
  if (status === "succeeded") return "Done";
  if (status === "failed") return "Failed";
  return "Pending";
}

export function BalancerOperationDialog({
  open,
  onOpenChange,
  title,
  description,
  steps,
  isRunning,
  summary,
  error,
  retryLabel = "Retry",
  onRetry
}: BalancerOperationDialogProps) {
  const completedSteps = steps.filter((step) => step.status === "succeeded").length;
  const progress = steps.length > 0 ? (completedSteps / steps.length) * 100 : 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (isRunning && !nextOpen) {
          return;
        }
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Progress value={progress} className="h-2" />

          <div className="space-y-2">
            {steps.map((step) => (
              <div
                key={step.id}
                className={cn(
                  "flex items-start justify-between gap-3 rounded-lg border p-3",
                  step.status === "failed"
                    ? "border-destructive/35 bg-destructive/5"
                    : "border-border/70 bg-muted/20"
                )}
              >
                <div className="flex min-w-0 gap-3">
                  <div className="mt-0.5">
                    <OperationStepIcon status={step.status} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{step.label}</div>
                    {step.description ? (
                      <div className="mt-0.5 text-xs text-muted-foreground">{step.description}</div>
                    ) : null}
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0">
                  {getStatusLabel(step.status)}
                </Badge>
              </div>
            ))}
          </div>

          {summary ? (
            <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-200">
              {summary}
            </div>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-destructive/35 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          {error && onRetry ? (
            <Button type="button" variant="outline" onClick={onRetry}>
              <RotateCcw className="mr-2 h-4 w-4" />
              {retryLabel}
            </Button>
          ) : null}
          <Button type="button" onClick={() => onOpenChange(false)} disabled={isRunning}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
