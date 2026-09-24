"use client";

import { useCallback, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useUnsavedGuard } from "@/components/kit/useUnsavedGuard";
import { Spinner } from "@/components/ui/spinner";

export interface SaveBarProps {
  dirty: boolean;
  /**
   * Whether leaving would LOSE something, arming the unsaved guard. Defaults
   * to `dirty`.
   *
   * The two differ on a form that opens prefilled from somewhere else — a
   * pick-ban scope carrying the rules it inherits, say. Saving there stores
   * values the organizer never typed, so the bar has work to offer; leaving
   * discards nothing they authored, so a discard prompt is a false alarm that
   * makes clicking through the scope tree cost a dialog per scope.
   */
  edited?: boolean;
  /** What is about to be saved: "3 changed fields", "v4 draft · 9 divisions". */
  summary: ReactNode;
  onDiscard: () => void;
  onSave: () => void;
  saving?: boolean;
  /** Overrides the default "Save changes"; e.g. "Save rules". */
  primaryLabel?: string;
  secondary?: ReactNode;
  /**
   * While dirty, intercept internal link clicks anywhere in the document so
   * leaving the page goes through the discard prompt. Defaults to `true`.
   *
   * Pass `false` when the screen's own routed sub-navigation is PART of this
   * form — `?section=` in the stage editor, `?tab=` in the divisions draft
   * editor. Those links do not unmount anything, so the prompt is a false
   * alarm that makes flipping between the sections of one form cost a
   * discard. The `beforeunload` half of the guard stays armed either way, so
   * a reload or a tab close is still caught; what the screen gives up is the
   * prompt on an in-app link that really does leave.
   */
  guardNavigation?: boolean;
}

/**
 * The save affordance for every T5 settings section.
 *
 * Sticky at the bottom and present only while dirty, so a clean form has no
 * dead "Save" button and a dirty one cannot be left behind by accident: it
 * shares `useUnsavedGuard` with `EntityFormDialog`, so navigating away goes
 * through the same discard prompt.
 *
 * Chrome matches `admin/BulkBar` and `ui/OverlayBar` -- the other two "act now"
 * bars -- a rounded, bordered, blurred card floating above the content it acts
 * on. It used to be a full-bleed strip with a top border only, which read as
 * the page's footer rather than as a transient control, and was the one element
 * of a settings screen not sitting in the card language around it.
 */
export function SaveBar({
  dirty,
  edited,
  summary,
  onDiscard,
  onSave,
  saving = false,
  primaryLabel,
  secondary,
  guardNavigation = true
}: Readonly<SaveBarProps>) {
  const t = useTranslations("admin.saveBar");
  const router = useRouter();
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  const handleNavigationBlocked = useCallback((href: string) => setPendingHref(href), []);

  useUnsavedGuard({
    dirty: (edited ?? dirty) && !saving,
    guardNavigation,
    onNavigationBlocked: handleNavigationBlocked
  });

  if (!dirty) return null;

  return (
    <>
      <div
        role="region"
        aria-label={t("unsavedChanges")}
        className="sticky bottom-4 z-10 mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/80"
      >
        <p className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{summary}</p>
        {secondary}
        <Button type="button" variant="outline" size="sm" onClick={onDiscard} disabled={saving}>
          {t("discard")}
        </Button>
        <Button type="button" size="sm" onClick={onSave} disabled={saving}>
          {saving ? <Spinner /> : null}
          {primaryLabel ?? t("save")}
        </Button>
      </div>

      <ConfirmDialog
        open={pendingHref !== null}
        onOpenChange={(open) => (open ? undefined : setPendingHref(null))}
        intent={{
          title: t("discardTitle"),
          description: t("discardDescription"),
          confirmLabel: t("discardConfirm"),
          tone: "warning"
        }}
        onConfirm={() => {
          const href = pendingHref;
          setPendingHref(null);
          onDiscard();
          if (href) router.push(href);
        }}
      />
    </>
  );
}
