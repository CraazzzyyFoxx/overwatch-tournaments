"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface BulkBarProps {
  /** How many rows the actions will apply to. Zero renders nothing. */
  count: number;
  /** Plural noun for the selection, e.g. "registrations". */
  unit: string;
  onClear: () => void;
  children: ReactNode;
}

/**
 * The bottom bar that appears while rows are selected (F4 ·3).
 *
 * Same visual register as `kit/SaveBar`: a bar that exists only while there is
 * something to act on, holding a summary on the left and the actions on the
 * right. It is `fixed` rather than `sticky` because `AdminDataTable` renders
 * `bulkActions` inside its toolbar row — which is exactly where bulk actions
 * used to be mistaken for filters, and the reason they moved down here.
 */
export function BulkBar({ count, unit, onClear, children }: Readonly<BulkBarProps>) {
  if (count === 0) return null;

  return (
    <div
      role="region"
      aria-label="Bulk actions"
      className="fixed bottom-4 left-1/2 z-30 flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/80"
    >
      <p className="text-sm text-muted-foreground">
        <span className="font-medium tabular-nums text-foreground">{count}</span> {unit} selected
      </p>
      {children}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7"
        aria-label="Clear selection"
        onClick={onClear}
      >
        <X aria-hidden className="size-4" />
      </Button>
    </div>
  );
}
