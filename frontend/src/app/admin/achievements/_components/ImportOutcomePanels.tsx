"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AchievementRuleImportResult } from "@/types/admin.types";

/** A file that never reached the API: wrong file, or hand-edited JSON. */
export function ImportErrorPanel({
  message,
  onDismiss,
}: Readonly<{ message: string; onDismiss: () => void }>) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 p-4">
      <p className="text-sm text-danger">{message}</p>
      <Button
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        aria-label="Dismiss the import error"
      >
        <X className="h-4 w-4" aria-hidden />
      </Button>
    </div>
  );
}

/**
 * What an import actually did. Warnings are per-slug and can run long, so they
 * scroll rather than pushing the table off screen.
 */
export function ImportResultPanel({
  result,
  onDismiss,
}: Readonly<{ result: AchievementRuleImportResult; onDismiss: () => void }>) {
  return (
    <div className="rounded-lg border p-4 bg-muted/50 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-medium">
          Import result
          <span className="ml-2 text-sm text-muted-foreground tabular-nums">
            created +{result.created} · updated {result.updated}
          </span>
        </p>
        <Button
          variant="ghost"
          size="icon"
          onClick={onDismiss}
          aria-label="Dismiss the import summary"
        >
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      {result.warnings.length > 0 && (
        <ScrollArea className="h-28 rounded border bg-background px-3 py-2">
          <div className="space-y-1 text-sm">
            {result.warnings.map((warning, index) => (
              <p key={`${warning.slug}-${index}`}>
                <span className="font-medium">{warning.slug}:</span> {warning.message}
              </p>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
