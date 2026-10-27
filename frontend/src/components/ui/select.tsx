"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { selectTriggerClass, triggerChevronClass } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import {
  floatingPanelClass,
  floatingPanelFadeClass,
  floatingRowClass
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type SelectSize = "sm" | "default";

/**
 * The trigger's `size`, handed to the list so its rows take the same text
 * (DESIGN §3, Control text) without a second prop at every call site.
 */
const SelectSizeContext = React.createContext<{
  size: SelectSize;
  setSize: (size: SelectSize) => void;
} | null>(null);

function Select(props: React.ComponentProps<typeof SelectPrimitive.Root>) {
  const [size, setSize] = React.useState<SelectSize>("default");
  const context = React.useMemo(() => ({ size, setSize }), [size]);
  return (
    <SelectSizeContext.Provider value={context}>
      <SelectPrimitive.Root {...props} />
    </SelectSizeContext.Provider>
  );
}

const SelectGroup = SelectPrimitive.Group;

const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger> & {
    size?: SelectSize;
    variant?: "default" | "surface";
  }
>(({ className, children, onPointerDown, size = "default", variant, ...props }, ref) => {
  const setSize = React.useContext(SelectSizeContext)?.setSize;
  React.useEffect(() => setSize?.(size), [setSize, size]);
  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(selectTriggerClass(size, variant), className)}
      // Radix opens on pointerdown and honours only its own `disabled`, but the
      // browser still dispatches pointerdown to a button disabled by an ancestor
      // `<fieldset disabled>` — so a locked select would open anyway.
      onPointerDown={(event) => {
        onPointerDown?.(event);
        if (event.currentTarget.matches(":disabled")) event.preventDefault();
      }}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className={triggerChevronClass} />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
});
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-1", className)}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", sideOffset = 4, ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-50 max-h-[min(18rem,var(--radix-select-content-available-height))] min-w-[8rem] overflow-y-auto overflow-x-hidden",
        floatingPanelClass,
        floatingPanelFadeClass,
        className
      )}
      position={position}
      sideOffset={sideOffset}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-1",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-2 pb-1 pt-2", eyebrowClass(), className)}
    {...props}
  />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => {
  const size = React.useContext(SelectSizeContext)?.size;
  return (
    <SelectPrimitive.Item
      ref={ref}
      className={cn(
        floatingRowClass,
        "w-full pr-8 focus:bg-[color:var(--aqt-overlay-4)] focus:text-[color:var(--aqt-fg)] data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
        size === "sm" && "text-caption",
        className
      )}
      {...props}
    >
      <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="h-4 w-4 text-[color:var(--aqt-teal)]" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
});
SelectItem.displayName = SelectPrimitive.Item.displayName;

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-[color:var(--aqt-overlay-border)]", className)}
    {...props}
  />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator
};
