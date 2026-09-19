"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { useUnsavedGuard } from "@/components/kit/useUnsavedGuard";
import { cn } from "@/lib/utils";

interface EntityFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  onSubmit: (e: React.FormEvent) => void;
  submitLabel?: string;
  cancelLabel?: string;
  isSubmitting?: boolean;
  submittingLabel?: string;
  errorMessage?: string;
  /**
   * Per-field validation messages keyed by field name. Listed in the dialog's
   * error region so every problem is announced in one pass; pair the same
   * message with `aria-invalid` / `aria-describedby` on the field itself.
   */
  fieldErrors?: Record<string, string>;
  isDirty?: boolean;
  dirtyTitle?: string;
  dirtyDescription?: string;
  /**
   * While the form is dirty, intercept internal link clicks anywhere in the
   * document so leaving the page goes through the discard prompt. Defaults to
   * `true`; pass `false` when this dialog should not reach outside itself.
   */
  guardNavigation?: boolean;
  contentClassName?: string;
  children: React.ReactNode;
  isReadOnly?: boolean;
}

export function EntityFormDialog({
  open,
  onOpenChange,
  title,
  description,
  onSubmit,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  isSubmitting = false,
  submittingLabel = "Saving…",
  errorMessage,
  fieldErrors,
  isDirty = false,
  dirtyTitle = "Discard unsaved changes?",
  dirtyDescription = "You have unsaved changes in this form. Leave now and the current edits will be lost.",
  guardNavigation = true,
  contentClassName,
  children,
  isReadOnly = false,
}: Readonly<EntityFormDialogProps>) {
  const router = useRouter();
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  const [pendingNavigationHref, setPendingNavigationHref] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // React portals bubble events through the React tree, not the DOM tree, so
    // this submit would otherwise reach the onSubmit of any form this dialog is
    // rendered from — e.g. the tournament settings form behind its integrations
    // card.
    e.stopPropagation();
    if (isReadOnly) {
      return;
    }
    onSubmit(e);
  };

  const handleNavigationBlocked = useCallback((href: string) => {
    setPendingNavigationHref(href);
    setDiscardDialogOpen(true);
  }, []);

  // `beforeunload` arms on dirty alone; the in-app link interception also
  // stands down while submitting or read-only, exactly as it did when both
  // effects lived in this file.
  useUnsavedGuard({
    dirty: open && isDirty,
    guardNavigation: guardNavigation && !isSubmitting && !isReadOnly,
    onNavigationBlocked: handleNavigationBlocked
  });

  const handleCancel = () => {
    if (isSubmitting) {
      return;
    }

    if (isDirty && !isReadOnly) {
      setDiscardDialogOpen(true);
      return;
    }

    onOpenChange(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      onOpenChange(true);
      return;
    }

    handleCancel();
  };

  const handleDiscardConfirm = () => {
    setDiscardDialogOpen(false);
    const nextHref = pendingNavigationHref;
    setPendingNavigationHref(null);
    onOpenChange(false);
    if (nextHref) {
      router.push(nextHref);
    }
  };

  const fieldErrorEntries = Object.entries(fieldErrors ?? {});

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent
          className={cn(
            "flex max-h-[calc(100dvh-2rem)] max-w-2xl flex-col gap-0 overflow-hidden sm:max-h-[90dvh]",
            contentClassName
          )}
        >
          <DialogHeader className="shrink-0 border-b border-border/60 pb-4">
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>

          <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-y-auto pr-4">
              <div className="space-y-4 py-4">{children}</div>
            </div>

            {errorMessage || fieldErrorEntries.length > 0 ? (
              <div
                role="alert"
                className="mt-4 flex shrink-0 items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
              >
                <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="space-y-1">
                  <p className="font-medium">Could not save your changes.</p>
                  {errorMessage ? <p>{errorMessage}</p> : null}
                  {fieldErrorEntries.length > 0 ? (
                    <ul className="list-inside list-disc space-y-0.5">
                      {fieldErrorEntries.map(([field, message]) => (
                        <li key={field}>{message}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            ) : null}

            <DialogFooter className="mt-4 shrink-0 border-t border-border/60 pt-4">
              <Button type="button" variant="outline" onClick={handleCancel} disabled={isSubmitting}>
                {isReadOnly && cancelLabel === "Cancel" ? "Close" : cancelLabel}
              </Button>
              {!isReadOnly && (
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
                      {submittingLabel}
                    </>
                  ) : (
                    submitLabel
                  )}
                </Button>
              )}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{dirtyTitle}</AlertDialogTitle>
            <AlertDialogDescription>{dirtyDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingNavigationHref(null)}>Keep editing</AlertDialogCancel>
            <AlertDialogAction onClick={handleDiscardConfirm}>Discard changes</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
