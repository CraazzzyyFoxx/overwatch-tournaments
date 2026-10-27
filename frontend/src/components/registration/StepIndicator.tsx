"use client";

import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface Step {
  label: string;
}

interface StepIndicatorProps {
  steps: Step[];
  current: number;
  onSelect: (index: number) => void;
}

export default function StepIndicator({ steps, current, onSelect }: Readonly<StepIndicatorProps>) {
  return (
    <div className="flex items-center justify-center gap-1">
      {steps.map((step, i) => {
        const isCompleted = i < current;
        const isActive = i === current;
        return (
          <div key={step.label} className="flex items-center gap-1">
            {i > 0 && (
              <Separator
                className={cn(
                  "w-8 transition-colors",
                  isCompleted
                    ? "bg-[color:var(--aqt-fg-dim)]"
                    : "bg-[color:var(--aqt-border-2)]",
                )}
              />
            )}
            <Button
              type="button"
              variant="ghost"
              size="inline"
              onClick={() => onSelect(i)}
              className="group gap-1.5 rounded-full sm:pr-2"
              aria-current={isActive ? "step" : undefined}
            >
              <div
                className={cn(
                  "flex size-6 items-center justify-center rounded-full text-xs font-medium transition-all",
                  isActive
                    ? "bg-[color:var(--aqt-teal)] text-[color:var(--aqt-bg)]"
                    : isCompleted
                      ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]"
                    : "bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-muted)]",
                )}
              >
                {isCompleted ? <Check className="size-3.5" aria-hidden /> : i + 1}
              </div>
              <span
                className={cn(
                  "sr-only text-xs font-medium sm:not-sr-only sm:inline",
                  isActive
                    ? "text-[color:var(--aqt-fg)]"
                    : "text-[color:var(--aqt-fg-muted)] group-hover:text-[color:var(--aqt-fg)]",
                )}
              >
                {step.label}
              </span>
            </Button>
          </div>
        );
      })}
    </div>
  );
}
