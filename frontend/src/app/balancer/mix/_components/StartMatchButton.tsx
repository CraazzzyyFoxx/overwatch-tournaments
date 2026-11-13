"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Play } from "lucide-react";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { Switch } from "@/components/ui/switch";

/**
 * Start match (spec §5.1), on a lobby's card and in its room alike. With bans the host sees who bans first (spec §8.3)
 * and may swap it; an away player still seated is named but does not block. Otherwise it starts at once.
 */
export function StartMatchButton({
  awayNames,
  opener,
  starting,
  onStart,
  variant = "default",
}: Readonly<{
  awayNames: readonly string[];
  /** The two lineup team names and the index of the one that bans first; null without bans. */
  opener: { names: readonly [string, string]; index: number } | null;
  starting: boolean;
  onStart: (flipOpener: boolean) => void;
  /** `accent` where it is one card's next step among several (the multi-lobby overview); `default` in the room. */
  variant?: "default" | "accent";
}>) {
  const t = useTranslations("mixes.room");
  const [open, setOpen] = useState(false);
  const [flip, setFlip] = useState(false);
  const first = opener == null ? null : opener.names[flip ? 1 - opener.index : opener.index];
  return (
    <>
      <Button
        type="button"
        variant={variant}
        size="sm"
        disabled={starting}
        onClick={() => (opener != null || awayNames.length > 0 ? setOpen(true) : onStart(false))}
      >
        {starting ? <Spinner className="mr-1.5 size-3.5" /> : <Play className="mr-1.5 size-3.5" aria-hidden="true" />}
        {t("startMatch")}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setFlip(false);
        }}
        intent={{
          title: t(opener != null ? "startTitle" : "awayTitle"),
          description: (
            <div className="flex flex-col gap-3">
              {awayNames.length > 0 ? <p>{t("awayDescription", { names: awayNames.join(", ") })}</p> : null}
              {first != null ? (
                <>
                  <p>{t("opener", { team: first })}</p>
                  <div className="flex items-center gap-2">
                    <Switch checked={flip} onCheckedChange={setFlip} aria-label={t("swapOpener")} />
                    <span className="text-caption text-[color:var(--aqt-fg-muted)]">{t("swapOpener")}</span>
                  </div>
                </>
              ) : null}
            </div>
          ),
          confirmLabel: t(opener != null ? "startConfirm" : "awayConfirm"),
          tone: awayNames.length > 0 ? "warning" : "neutral",
        }}
        pending={starting}
        onConfirm={() => {
          setOpen(false);
          setFlip(false);
          onStart(flip);
        }}
      />
    </>
  );
}
