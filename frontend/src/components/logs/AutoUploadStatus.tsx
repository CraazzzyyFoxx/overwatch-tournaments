"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { directoryErrorCode } from "@/lib/logs/browser-directory";
import { useLogAutoUploadStore } from "@/lib/logs/use-log-auto-upload";
import { cn } from "@/lib/utils";

const TONE_BY_STATE: Record<"idle" | "watching" | "permission" | "error", Tone> = {
  idle: "neutral",
  watching: "accent",
  permission: "warning",
  error: "danger"
};

/**
 * The live line of the automatic upload: what the watcher is doing right now.
 * `idle` is the context's own sentence for "no watcher in this tab" — another
 * tab on a tournament page, or no tournament page open at all.
 */
export function AutoUploadStatus({
  folder,
  idle,
  target
}: Readonly<{ folder: string; idle: string; target?: string }>) {
  const t = useTranslations("accountSettings.logDirectory");
  const { holder, status, error, grant } = useLogAutoUploadStore();
  const state = holder == null ? "idle" : status;
  const title = {
    idle,
    watching: t("auto.watching", { folder }),
    permission: t("auto.permission"),
    error: t(`errors.${directoryErrorCode(error)}`)
  }[state];

  return (
    <div className="flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-3.5 py-3">
      <span aria-hidden className={cn("relative flex size-2.5 shrink-0", TONE_TEXT[TONE_BY_STATE[state]])}>
        {state === "watching" ? (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60 motion-reduce:hidden" />
        ) : null}
        <span className="relative inline-flex size-2.5 rounded-full bg-current" />
      </span>
      <div className="min-w-0 flex-1" role="status">
        <p className="text-ui font-semibold text-[color:var(--aqt-fg)]">{title}</p>
        {state === "watching" && target ? (
          <p className="text-caption text-pretty text-[color:var(--aqt-fg-muted)]">{target}</p>
        ) : null}
      </div>
      {state === "permission" && grant ? (
        <Button type="button" size="sm" variant="outline" onClick={grant}>
          {t("auto.grant")}
        </Button>
      ) : null}
    </div>
  );
}
