"use client";

import * as React from "react";
import { type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { segmentedFrame, toggleVariants } from "@/components/ui/toggle";

type ToggleGroupProps = Omit<React.ComponentProps<"div">, "defaultValue" | "onChange"> &
  VariantProps<typeof toggleVariants> & {
    value?: string;
    onValueChange?: (value: string) => void;
  };

type ToggleGroupItemProps = Omit<React.ComponentProps<"button">, "value"> &
  VariantProps<typeof toggleVariants> & {
    value: string;
    /** Colour of the on state instead of teal (`pill`, `card`): a CSS colour or token, e.g. a role's hue. */
    accent?: string;
  };

const ToggleGroupContext = React.createContext<{
  value?: string;
  onValueChange?: (value: string) => void;
  variant?: VariantProps<typeof toggleVariants>["variant"];
  size?: VariantProps<typeof toggleVariants>["size"];
  /** Roving focus is only safe once one item owns the group's tab stop. */
  roving?: boolean;
  /**
   * With nothing selected, the first enabled option holds the tab stop (APG
   * radio group). `null` when the options are not direct children, so their
   * values cannot be read: then every option stays tabbable.
   */
  firstValue?: string | null;
}>({});

/** Arrow keys that move within a radiogroup, and the direction each one moves. */
const ARROW_STEP: Record<string, number> = {
  ArrowRight: 1,
  ArrowDown: 1,
  ArrowLeft: -1,
  ArrowUp: -1
};

/** The first enabled direct child's `value`, or `null` when none is readable. */
function firstOptionValue(children: React.ReactNode): string | null {
  for (const child of React.Children.toArray(children)) {
    if (!React.isValidElement<{ value?: unknown; disabled?: boolean }>(child)) continue;
    if (typeof child.props.value === "string" && !child.props.disabled) return child.props.value;
  }
  return null;
}

/**
 * Single-select segmented control.
 *
 * The items are radios, so the container must be a `radiogroup` and the group
 * must behave like one: exactly one tab stop, arrow keys moving *and* selecting
 * (ARIA APG radio-group pattern). Both the group and its items take any DOM
 * prop and a `ref`, so an item can sit under `TooltipTrigger asChild`.
 */
function ToggleGroup({
  className,
  variant,
  size,
  value,
  onValueChange,
  children,
  onKeyDown,
  ...props
}: Readonly<ToggleGroupProps>) {
  const roving = value != null && value !== "";
  const firstValue = roving ? null : firstOptionValue(children);

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    onKeyDown?.(event);
    const step = ARROW_STEP[event.key];
    if (step === undefined) return;

    const items = [
      ...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')
    ].filter((item) => !item.disabled);
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (current === -1) return;

    event.preventDefault();
    const next = items[(current + step + items.length) % items.length];
    next.focus();
    next.click();
  }

  return (
    <ToggleGroupContext.Provider
      value={{ value, onValueChange, variant, size, roving, firstValue }}
    >
      <div
        {...props}
        role="radiogroup"
        onKeyDown={handleKeyDown}
        className={cn(
          "flex items-center",
          variant === "card"
            ? // Separate cards: the caller's `grid-cols-*` lays them out.
              "grid items-stretch gap-2 aria-invalid:*:border-destructive"
            : segmentedFrame,
          className
        )}
      >
        {children}
      </div>
    </ToggleGroupContext.Provider>
  );
}

function ToggleGroupItem({
  className,
  value,
  variant,
  size,
  accent,
  style,
  onClick,
  ...props
}: Readonly<ToggleGroupItemProps>) {
  const context = React.useContext(ToggleGroupContext);
  const isOn = context.value === value;

  // The caller's props first: a `TooltipTrigger asChild` hands its own
  // `data-state` down, which must not replace the on/off one.
  return (
    <button
      type="button"
      {...props}
      role="radio"
      aria-checked={isOn}
      data-state={isOn ? "on" : "off"}
      tabIndex={
        context.roving
          ? isOn
            ? 0
            : -1
          : context.firstValue == null || context.firstValue === value
            ? 0
            : -1
      }
      onClick={(event) => {
        onClick?.(event);
        context.onValueChange?.(value);
      }}
      style={accent ? ({ "--toggle-accent": accent, ...style } as React.CSSProperties) : style}
      className={cn(
        toggleVariants({
          variant: context.variant || variant,
          size: context.size || size
        }),
        className
      )}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
