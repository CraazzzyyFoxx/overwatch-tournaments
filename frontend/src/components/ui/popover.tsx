"use client";

import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import { cn } from "@/lib/utils";

const Popover = PopoverPrimitive.Root;

const PopoverTrigger = PopoverPrimitive.Trigger;

const PopoverAnchor = PopoverPrimitive.Anchor;

const PopoverClose = PopoverPrimitive.Close;

/**
 * The floating panel every overlay shares: select and combobox lists, menus,
 * popovers and (at a smaller radius) tooltips. Raised off whatever it opens
 * over, like an `outline` button: the `--aqt-card-2` fill is lighter than a
 * page, a card or a dialog, with the control border and the 1px light along
 * its top edge. No drop shadow (DESIGN §5).
 */
export const floatingPanelClass =
  "rounded-[10px] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] text-[color:var(--aqt-fg)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)]";

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content> & { animate?: boolean }
>(
  (
    {
      className,
      align = "center",
      sideOffset = 4,
      animate = true,
      onWheelCapture,
      onTouchMove,
      ...props
    },
    ref
  ) => (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        // Keep wheel/touch inside the popover, or a scrollable body of one opened
        // from a modal Dialog cannot scroll at all.
        //
        // Radix Dialog wraps its content in react-remove-scroll, which registers a
        // NON-capture `wheel`/`touchmove` listener on `document`. That listener
        // preventDefaults any event it cannot attribute to the locked subtree or to
        // a declared shard — and this content is portalled to `document.body`, so
        // it is neither. The default scroll action runs only after dispatch
        // finishes, so the list never moves even though it overflows.
        //
        // Radix Select/DropdownMenu are unaffected: each is modal in its own right
        // and installs its own lock, which registers its content. Popover is not,
        // so it has to keep the event away from `document` itself.
        onWheelCapture={(event) => {
          onWheelCapture?.(event);
          event.stopPropagation();
        }}
        onTouchMove={(event) => {
          onTouchMove?.(event);
          event.stopPropagation();
        }}
        className={cn(
          "z-50 w-72 p-4 outline-none",
          floatingPanelClass,
          animate &&
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
);
PopoverContent.displayName = PopoverPrimitive.Content.displayName;

export { Popover, PopoverTrigger, PopoverContent, PopoverAnchor, PopoverClose };
