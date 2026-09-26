"use client";

import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TONE_TEXT } from "@/components/kit/tone";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

export type ConfirmTone = "danger" | "warning" | "neutral";

export interface ConfirmIntent {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  tone: ConfirmTone;
  /** Records removed alongside the object; listed under the description. */
  cascade?: string[];
  /** Enables the button only once the user types this exactly (a name). */
  requireTyped?: string;
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  intent: ConfirmIntent;
  onConfirm: () => Promise<void> | void;
  pending?: boolean;
}

const TONE_ICON: Record<ConfirmTone, string> = {
  danger: TONE_TEXT.danger,
  warning: TONE_TEXT.warning,
  neutral: TONE_TEXT.neutral
};

/**
 * The single confirmation surface for the whole app — admin screens, the site
 * and the tools alike.
 *
 * One instance per screen with a swapped `intent`. That is what replaced the
 * six near-identical delete-confirmation mounts in the old stage manager —
 * each a copy of the same markup differing only in its strings.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  intent,
  onConfirm,
  pending = false
}: Readonly<ConfirmDialogProps>) {
  const typedFieldId = useId();
  const t = useTranslations("common");
  const [typed, setTyped] = useState("");

  // A reused instance must not carry the previous intent's typed value into
  // the next confirmation. Adjusted during render rather than in an effect:
  // the value is derived from `open`/`requireTyped`, so an effect would commit
  // one render with the stale text before clearing it.
  const [seen, setSeen] = useState({ open, requireTyped: intent.requireTyped });
  if (seen.open !== open || seen.requireTyped !== intent.requireTyped) {
    setSeen({ open, requireTyped: intent.requireTyped });
    if (!open) setTyped("");
  }

  const typedOk = intent.requireTyped === undefined || typed.trim() === intent.requireTyped;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle aria-hidden className={cn("size-5", TONE_ICON[intent.tone])} />
            <AlertDialogTitle>{intent.title}</AlertDialogTitle>
          </div>
          <AlertDialogDescription asChild>
            <div>{intent.description}</div>
          </AlertDialogDescription>
          {intent.cascade && intent.cascade.length > 0 ? (
            <div className="mt-4 rounded-md border border-danger/20 bg-danger/10 p-3">
              <p className="mb-2 font-medium text-danger">{t("confirm.cascade")}</p>
              <ul className="list-inside list-disc space-y-1 text-sm">
                {intent.cascade.map((entry) => (
                  <li key={entry}>{entry}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </AlertDialogHeader>

        {intent.requireTyped !== undefined ? (
          <div className="space-y-1.5">
            <Label htmlFor={typedFieldId}>
              {t.rich("confirm.typeToConfirm", {
                name: intent.requireTyped,
                code: (chunks) => <span className="font-mono">{chunks}</span>
              })}
            </Label>
            <Input
              id={typedFieldId}
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
        ) : null}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={(event) => {
              event.preventDefault();
              void onConfirm();
            }}
            disabled={pending || !typedOk}
            // `destructive` is the solid-button role; `danger` is its text tone
            // (see the comment on the tone scales in `globals.css`).
            className={cn(
              intent.tone === "danger" &&
                "bg-destructive text-destructive-foreground hover:bg-destructive/90"
            )}
          >
            {pending ? <Spinner /> : null}
            {intent.confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
