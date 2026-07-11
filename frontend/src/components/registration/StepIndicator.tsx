"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

interface Step {
  label: string;
}

interface StepIndicatorProps {
  steps: Step[];
  current: number;
}

export default function StepIndicator({ steps, current }: StepIndicatorProps) {
  return (
    <div className="flex items-center justify-center gap-1">
      {steps.map((step, i) => {
        const isCompleted = i < current;
        const isActive = i === current;
        return (
          <div key={i} className="flex items-center gap-1">
            {i > 0 && (
              <div
                className={cn(
                  "h-px w-8 transition-colors",
                  isCompleted ? "bg-white/30" : "bg-white/8",
                )}
              />
            )}
            <div className="flex items-center gap-1.5">
              <div
                className={cn(
                  "flex size-6 items-center justify-center rounded-full text-xs font-medium transition-all",
                  isActive
                    ? "bg-white text-black"
                    : isCompleted
                      ? "bg-white/20 text-[color:var(--aqt-fg-muted)]"
                      : "bg-white/5 text-[color:var(--aqt-fg-faint)]",
                )}
              >
                {isCompleted ? <Check className="size-3.5" /> : i + 1}
              </div>
              <span
                className={cn(
                  "hidden text-xs font-medium sm:inline",
                  isActive ? "text-[color:var(--aqt-fg)]" : isCompleted ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg-faint)]",
                )}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
