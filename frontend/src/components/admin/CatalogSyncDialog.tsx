"use client";

import type { ReactNode } from "react";
import { Check, Circle, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import type { CatalogSync } from "@/hooks/useCatalogSync";
import { useKindLabel } from "@/hooks/useKindLabel";
import { getApiErrorMessage } from "@/lib/api/error";
import { cn } from "@/lib/utils";
import type { CatalogSyncStage } from "@/types/catalog.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/** Decorative: every row also names its state in words. */
const STAGE_ICON: Record<CatalogSyncStage["state"], ReactNode> = {
  pending: <Circle aria-hidden className="size-4 text-muted-foreground" />,
  running: <Spinner />,
  done: <Check aria-hidden className={cn("size-4", TONE_TEXT.success)} />,
  failed: <X aria-hidden className={cn("size-4", TONE_TEXT.danger)} />
};

/**
 * A discipline's background catalog sync: one row per stage, the outcome, and Retry when it did not finish. Closing
 * it never stops the sync. Opened by `useCatalogSync` only, never on mount.
 */
export function CatalogSyncDialog({
  descriptor,
  sync
}: Readonly<{ descriptor: DisciplineDescriptor; sync: CatalogSync }>) {
  const t = useTranslations("adminWorkspace.content.catalog.sync");
  const kindLabel = useKindLabel();
  const { state, interrupted, startError } = sync;
  const failed = startError != null || interrupted || state?.status === "failed";
  const running = !failed && state?.status === "running";

  let status = t("running");
  let detail: string | undefined;
  if (startError) {
    status = t("startError");
    detail = getApiErrorMessage(startError);
  } else if (interrupted || state?.error?.code === "interrupted") {
    status = t("interrupted");
    // Only the server's own verdict has a reason; a worker that vanished left none.
    detail = state?.error?.msg;
  } else if (state?.status === "failed") {
    status = t(state.error?.code === "catalog_source_unavailable" ? "sourceUnavailable" : "failed");
    detail = state.error?.msg;
  } else if (state?.status === "done") {
    status = t("done");
  }

  return (
    <Dialog open={sync.open} onOpenChange={sync.setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title", { game: descriptor.name })}</DialogTitle>
          <DialogDescription aria-live="polite">
            {status}
            {detail ? <span className="block">{detail}</span> : null}
          </DialogDescription>
        </DialogHeader>

        {/* A start that failed has no run of its own: the last snapshot would only mislead. */}
        {state && !startError ? (
          <ol className="space-y-2">
            {state.stages.map((stage) => {
              // A dead worker leaves its last stage "running"; it is not spinning any more.
              const stageState = interrupted && stage.state === "running" ? "failed" : stage.state;
              let note: string | null = null;
              if (stageState === "running" && (stage.total ?? 0) > 0) {
                note = t("images", { done: stage.done ?? 0, total: stage.total ?? 0 });
              } else if (stageState === "done" && stage.created != null) {
                note = t("created", { created: stage.created });
              }
              return (
                <li key={stage.key} className="flex items-center gap-3 text-sm">
                  {STAGE_ICON[stageState]}
                  <span className="flex-1">
                    {stage.key === "source"
                      ? state.source
                        ? t("stageSource", { source: state.source })
                        : t("stageSourceUnknown")
                      : kindLabel(descriptor, stage.key)}
                    <span className="sr-only"> — {t(`states.${stageState}`)}</span>
                  </span>
                  {note ? <span className="tabular-nums text-muted-foreground">{note}</span> : null}
                </li>
              );
            })}
          </ol>
        ) : null}

        {sync.startedByOther ? <p className="text-xs text-muted-foreground">{t("startedByOther")}</p> : null}

        <DialogFooter>
          <Button variant={failed ? "outline" : "default"} onClick={() => sync.setOpen(false)}>
            {running ? t("hide") : t("close")}
          </Button>
          {failed ? <Button onClick={sync.start}>{t("retry")}</Button> : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
