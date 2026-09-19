"use client";

import type { ReactNode } from "react";
import { Check, ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type WizardStepState = "done" | "current" | "todo" | "skipped";

export interface WizardStep {
  key: string;
  label: string;
  state: WizardStepState;
}

export interface WizardShellProps {
  steps: WizardStep[];
  children: ReactNode;
  footer: {
    back?: () => void;
    next?: { label: string; onClick: () => void; disabled?: boolean };
    secondary?: ReactNode;
  };
  /** Slot under the step rail: past sessions (F5), "import instead" (F16). */
  aside?: ReactNode;
}

/**
 * The T6 wizard frame: step rail, one step's content, one footer.
 *
 * A `skipped` step renders dimmed and WITHOUT a number, so a flow that skips
 * "Conflicts" does not silently renumber the steps after it.
 */
export function WizardShell({ steps, children, footer, aside }: Readonly<WizardShellProps>) {
  // Numbering is resolved up front rather than accumulated inside the `map`
  // callback: a counter mutated from a render callback is a side effect the
  // compiler cannot reason about (it depends on how many times the callback
  // happens to run). The rule stays the same — a `skipped` step consumes no
  // number, so the steps after it keep the sequence the user has been reading.
  const numbers: number[] = [];
  let visibleNumber = 0;
  for (const step of steps) {
    if (step.state !== "skipped") visibleNumber += 1;
    numbers.push(visibleNumber);
  }

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="w-full shrink-0 lg:w-[220px]">
        <ol aria-label="Steps" className="space-y-0.5">
          {steps.map((step, index) => {
            const isSkipped = step.state === "skipped";
            const number = numbers[index];

            return (
              <li key={step.key}>
                <div
                  aria-current={step.state === "current" ? "step" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                    step.state === "current" && "bg-accent/40 font-medium text-foreground",
                    step.state === "done" && "text-foreground",
                    step.state === "todo" && "text-muted-foreground",
                    isSkipped && "text-muted-foreground/50"
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums",
                      step.state === "done"
                        ? "border-primary/50 bg-primary/15 text-primary"
                        : step.state === "current"
                          ? "border-primary text-primary"
                          : "border-border text-muted-foreground"
                    )}
                  >
                    {step.state === "done" ? (
                      <Check aria-hidden className="size-3" />
                    ) : isSkipped ? null : (
                      number
                    )}
                  </span>
                  <span className="truncate">{step.label}</span>
                  {isSkipped ? <span className="sr-only">(skipped)</span> : null}
                </div>
              </li>
            );
          })}
        </ol>
        {aside ? <div className="mt-4">{aside}</div> : null}
      </div>

      <div className="min-w-0 flex-1">
        <div className="min-w-0">{children}</div>

        <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-border pt-4">
          {footer.back ? (
            <Button type="button" variant="outline" size="sm" onClick={footer.back}>
              <ChevronLeft aria-hidden className="size-4" />
              Back
            </Button>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {footer.secondary}
            {footer.next ? (
              <Button
                type="button"
                size="sm"
                onClick={footer.next.onClick}
                disabled={footer.next.disabled}
              >
                {footer.next.label}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
