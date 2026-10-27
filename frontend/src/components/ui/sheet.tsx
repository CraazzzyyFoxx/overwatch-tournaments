"use client";

import * as React from "react";
import * as SheetPrimitive from "@radix-ui/react-dialog";
import { cva, type VariantProps } from "class-variance-authority";

import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  MODAL_SURFACE_CLASS,
  ModalCloseButton,
  PANEL_CONTENT_CLASS,
  type PanelVariant
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

// A sheet is a `Dialog` docked to an edge: the same Radix primitive, scrim,
// surface, header, footer, title and close button. Only the box differs, and
// it fades like every modal rather than sliding in (DESIGN §10).
const sheetVariants = cva(`fixed gap-4 ${MODAL_SURFACE_CLASS}`, {
  variants: {
    side: {
      top: "inset-x-0 top-0 max-h-[100dvh] border-b",
      bottom: "inset-x-0 bottom-0 max-h-[100dvh] border-t",
      left: "inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm",
      right: "inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm"
    }
  },
  defaultVariants: {
    side: "right"
  }
});

interface SheetContentProps
  extends
    React.ComponentPropsWithoutRef<typeof SheetPrimitive.Content>,
    VariantProps<typeof sheetVariants> {
  /** Panels that put their own close control in a header pass `false`. */
  closeButton?: boolean;
  /** `panel`: the flush work-surface chrome `DialogContent variant="panel"` documents. */
  variant?: PanelVariant;
}

const SheetContent = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Content>,
  SheetContentProps
>(
  (
    { side = "right", variant = "default", className, children, closeButton = true, ...props },
    ref
  ) => (
    <DialogPortal>
      <DialogOverlay />
      <SheetPrimitive.Content
        ref={ref}
        className={cn(
          sheetVariants({ side }),
          variant === "panel" && PANEL_CONTENT_CLASS,
          className
        )}
        {...props}
      >
        {children}
        {closeButton && <ModalCloseButton variant={variant} />}
      </SheetPrimitive.Content>
    </DialogPortal>
  )
);
SheetContent.displayName = SheetPrimitive.Content.displayName;

export {
  Dialog as Sheet,
  DialogTrigger as SheetTrigger,
  DialogClose as SheetClose,
  SheetContent,
  DialogHeader as SheetHeader,
  DialogFooter as SheetFooter,
  DialogTitle as SheetTitle,
  DialogDescription as SheetDescription
};
