"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { DryRunResult } from "../_hooks/useAchievementRuleActions";

/** Who would qualify for a rule right now, without awarding anything. */
export function DryRunResultDialog({
  result,
  onDismiss,
}: Readonly<{ result: DryRunResult | null; onDismiss: () => void }>) {
  return (
    <Dialog open={!!result} onOpenChange={(open) => !open && onDismiss()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dry-run result: {result?.slug}</DialogTitle>
          <DialogDescription>
            <span className="tabular-nums">{result?.count ?? 0}</span> users qualify for this
            achievement right now. Nothing was awarded.
          </DialogDescription>
        </DialogHeader>
        {result && result.sample.length > 0 && (
          <div className="text-sm">
            <p className="font-medium mb-2" id="dry-run-sample">Sample (first 20)</p>
            <div
              className="max-h-48 overflow-auto rounded border p-2 bg-muted/50 font-mono text-xs tabular-nums"
              tabIndex={0}
              role="group"
              aria-labelledby="dry-run-sample"
            >
              {result.sample.map((tuple, i) => (
                <div key={i}>
                  user={tuple[0]}
                  {tuple[1] ? ` tournament=${tuple[1]}` : ""}
                  {tuple[2] ? ` match=${tuple[2]}` : ""}
                </div>
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
