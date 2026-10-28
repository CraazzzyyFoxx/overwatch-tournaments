"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { floatingPanelFadeClass } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * One modal chrome for `Dialog`, `AlertDialog` and `Sheet` (DESIGN §5, §10):
 * the page colour as the scrim; the card fill, a hairline rim and the 1px lit
 * top edge as the surface, no drop shadow. Both fade in and out in ~150ms (the
 * floating panel's fade): no zoom, no slide.
 *
 * `overflow-auto` (not `overflow-y-auto`) so a modal taller than the viewport
 * scrolls instead of running off its edges. It shares tailwind-merge's
 * `overflow` group, so the surfaces that manage their own scrolling
 * (`overflow-hidden` + an inner scroller) still override it.
 */
const MODAL_OVERLAY_CLASS = `fixed inset-0 z-50 bg-background/80 ${floatingPanelFadeClass}`;
const MODAL_SURFACE_CLASS = `z-50 overflow-auto overscroll-contain border-border bg-card p-6 text-[color:var(--aqt-fg)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)] ${floatingPanelFadeClass}`;
/** The centred box: 12px radius, a 1rem margin from every viewport edge. */
const MODAL_CONTENT_CLASS = `fixed left-1/2 top-1/2 grid max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border ${MODAL_SURFACE_CLASS}`;
const MODAL_HEADER_CLASS = "flex flex-col space-y-1.5 text-start";
const MODAL_TITLE_CLASS = "text-heading font-semibold";
const MODAL_DESCRIPTION_CLASS = "text-body text-muted-foreground";

const Dialog = DialogPrimitive.Root;

const DialogTrigger = DialogPrimitive.Trigger;

const DialogPortal = DialogPrimitive.Portal;

const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay ref={ref} className={cn(MODAL_OVERLAY_CLASS, className)} {...props} />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

/**
 * `panel` is a work surface rather than a message: flush (no padding or gap),
 * a flex column that clips, so the body runs its own scroller between a header
 * and a footer ruled off by `DialogHeader`/`DialogFooter variant="panel"`.
 * `SheetContent` takes the same variant.
 */
type PanelVariant = "default" | "panel";

const PANEL_CONTENT_CLASS = "flex flex-col gap-0 overflow-hidden p-0";
const PANEL_HEADER_CLASS = "shrink-0 border-b border-[color:var(--aqt-border)] py-4 ps-5 pe-12";
const PANEL_FOOTER_CLASS = "shrink-0 border-t border-[color:var(--aqt-border)] px-5 py-3";

/**
 * The one close control of a modal: a quiet 28px icon button in the top-trailing
 * corner, centred on the title's first line; `DialogHeader` keeps clear of it.
 * `SheetContent` mounts the same one.
 */
function ModalCloseButton({ variant }: { variant: PanelVariant }) {
  const t = useTranslations("common");
  return (
    <DialogPrimitive.Close asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={t("close")}
        className={cn("absolute", variant === "panel" ? "end-3.5 top-3.5" : "end-4 top-5")}
      >
        <X aria-hidden />
      </Button>
    </DialogPrimitive.Close>
  );
}

interface DialogContentProps extends React.ComponentPropsWithoutRef<
  typeof DialogPrimitive.Content
> {
  variant?: PanelVariant;
  /** Panels that put their own close control in a header pass `false`. */
  closeButton?: boolean;
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, variant = "default", closeButton = true, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(MODAL_CONTENT_CLASS, variant === "panel" && PANEL_CONTENT_CLASS, className)}
      {...props}
    >
      {children}
      {closeButton && <ModalCloseButton variant={variant} />}
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

/** The `Sheet` header too; `pe-*` keeps clear of the close button (`AlertDialog` has none). */
const DialogHeader = ({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: PanelVariant }) => (
  <div
    className={cn(MODAL_HEADER_CLASS, variant === "panel" ? PANEL_HEADER_CLASS : "pe-7", className)}
    {...props}
  />
);

/** The `AlertDialog` and `Sheet` footer too: actions stacked (primary on top) on a phone, a trailing row from `sm`. */
const DialogFooter = ({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: PanelVariant }) => (
  <div
    className={cn(
      "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
      variant === "panel" && PANEL_FOOTER_CLASS,
      className
    )}
    {...props}
  />
);

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn(MODAL_TITLE_CLASS, className)} {...props} />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn(MODAL_DESCRIPTION_CLASS, className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogTrigger,
  DialogPortal,
  DialogClose,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  ModalCloseButton,
  MODAL_OVERLAY_CLASS,
  MODAL_SURFACE_CLASS,
  MODAL_CONTENT_CLASS,
  MODAL_HEADER_CLASS,
  MODAL_TITLE_CLASS,
  MODAL_DESCRIPTION_CLASS,
  PANEL_CONTENT_CLASS
};
export type { PanelVariant };
