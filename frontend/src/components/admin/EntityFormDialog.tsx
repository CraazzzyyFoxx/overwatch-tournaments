"use client";

import { useEffect, useState } from "react";
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
import {
  getInternalNavigationTarget,
  isChangedInternalNavigation,
  shouldIgnoreNavigationClick,
} from "@/lib/navigation-guard.mjs";
import { cn } from "@/lib/utils";

interface EntityFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  onSubmit: (e: React.FormEvent) => void;
  onCancel?: () => void;
  submitLabel?: string;
  cancelLabel?: string;
  isSubmitting?: boolean;
  submittingLabel?: string;
  errorMessage?: string;
  isDirty?: boolean;
  dirtyTitle?: string;
  dirtyDescription?: string;
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
  onCancel,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  isSubmitting = false,
  submittingLabel = "Saving…",
  errorMessage,
  isDirty = false,
  dirtyTitle = "Discard unsaved changes?",
  dirtyDescription = "You have unsaved changes in this form. Leave now and the current edits will be lost.",
  contentClassName,
  children,
  isReadOnly = false,
}: EntityFormDialogProps) {
  const router = useRouter();
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  const [pendingNavigationHref, setPendingNavigationHref] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isReadOnly) {
      return;
    }
    onSubmit(e);
  };

  useEffect(() => {
    if (!open || !isDirty) {
      return;
    }

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [isDirty, open]);

  useEffect(() => {
    if (!open || !isDirty || isSubmitting || isReadOnly) {
      return;
    }

    const handleDocumentClick = (event: MouseEvent) => {
      if (shouldIgnoreNavigationClick(event)) {
        return;
      }

      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      const anchor = target.closest("a[href]");
      if (!anchor) {
        return;
      }

      const href = anchor.getAttribute("href");
      if (!href || (anchor as HTMLAnchorElement).target === "_blank" || anchor.hasAttribute("download")) {
        return;
      }

      const nextTarget = getInternalNavigationTarget(href, window.location.origin);
      if (!nextTarget) {
        return;
      }

      const currentHref = window.location.href;
      if (!isChangedInternalNavigation(currentHref, href, window.location.origin)) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      setPendingNavigationHref(nextTarget);
      setDiscardDialogOpen(true);
    };

    document.addEventListener("click", handleDocumentClick, true);
    return () => {
      document.removeEventListener("click", handleDocumentClick, true);
    };
  }, [isDirty, isSubmitting, open, isReadOnly]);

  const closeDialog = () => {
    if (onCancel) {
      onCancel();
    } else {
      onOpenChange(false);
    }
  };

  const handleCancel = () => {
    if (isSubmitting) {
      return;
    }

    if (isDirty && !isReadOnly) {
      setDiscardDialogOpen(true);
      return;
    }

    closeDialog();
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
    closeDialog();
    if (nextHref) {
      router.push(nextHref);
    }
  };

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

            {errorMessage ? (
              <div
                aria-live="polite"
                role="alert"
                className="mt-4 flex shrink-0 items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="space-y-1">
                  <p className="font-medium">Save failed</p>
                  <p>{errorMessage}</p>
                </div>
              </div>
            ) : null}

            <DialogFooter className="mt-4 shrink-0 border-t border-border/60 pt-4">
              <Button type="button" variant="outline" onClick={handleCancel} disabled={isSubmitting}>
                {isReadOnly ? (cancelLabel === "Cancel" ? "Close" : cancelLabel) : cancelLabel}
              </Button>
              {!isReadOnly && (
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <LoaderCircle className="h-4 w-4 animate-spin" />
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
