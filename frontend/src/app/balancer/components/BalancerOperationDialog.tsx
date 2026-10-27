import { AlertTriangle, CheckCircle2, Circle, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { Spinner } from "@/components/ui/spinner";
import { TONE_TEXT } from "@/components/ui/tone";

import type { BalancerOperationStep, BalancerOperationStepStatus } from "./operation-steps";

type BalancerOperationDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  steps: BalancerOperationStep[];
  isRunning: boolean;
  summary: string | null;
  advisories?: string[];
  error: string | null;
  retryLabel?: string;
  onRetry?: () => void;
};

function OperationStepIcon({ status }: Readonly<{ status: BalancerOperationStepStatus }>) {
  if (status === "running") {
    return <Spinner className={TONE_TEXT.info} />;
  }

  if (status === "succeeded") {
    return <CheckCircle2 className={cn("h-4 w-4", TONE_TEXT.success)} />;
  }

  if (status === "failed") {
    return <AlertTriangle className="h-4 w-4 text-destructive" />;
  }

  return <Circle className="h-4 w-4 text-muted-foreground/55" />;
}

export function BalancerOperationDialog({
  open,
  onOpenChange,
  title,
  description,
  steps,
  isRunning,
  summary,
  advisories,
  error,
  retryLabel,
  onRetry
}: Readonly<BalancerOperationDialogProps>) {
  const t = useTranslations("balancerTool.page.operation");
  const tCommon = useTranslations("common");
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
          <Progress value={progress} aria-label={title} />

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
                    <div className="text-sm font-medium">{t(`steps.${step.id}.label`)}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {t(`steps.${step.id}.description`)}
                    </div>
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0">
                  {t(`stepStatus.${step.status}`)}
                </Badge>
              </div>
            ))}
          </div>

          {summary ? (
            <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-200">
              {summary}
            </div>
          ) : null}

          <div role="status">
            {advisories?.length ? (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                <div className="flex items-center gap-2 font-medium">
                  <AlertTriangle className="h-4 w-4" aria-hidden />
                  {t("advisories")}
                </div>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {advisories.map((advisory, index) => <li key={index}>{advisory}</li>)}
                </ul>
              </div>
            ) : null}
          </div>

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
              {retryLabel ?? tCommon("retry")}
            </Button>
          ) : null}
          <Button type="button" onClick={() => onOpenChange(false)} disabled={isRunning}>
            {tCommon("close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
