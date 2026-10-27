"use client";

import * as React from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useLocale } from "next-intl";
import { DayPicker, getDefaultClassNames, type DayButton } from "react-day-picker";
import { enUS, ru } from "react-day-picker/locale";

import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";

// Caption, weekday names, aria labels and week start come from the day
// picker's own (date-fns) locale, not from `Intl` — so it needs the UI's too.
const DAY_PICKER_LOCALES = { en: enUS, ru } as const;

/**
 * No fill of its own: the floating panel it opens in paints it (DESIGN §5).
 * The chosen day is the teal `accent` tint, today is teal text, a range's
 * middle the neutral overlay.
 */
function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  components,
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  const defaultClassNames = getDefaultClassNames();
  const locale = DAY_PICKER_LOCALES[useLocale()];

  return (
    <DayPicker
      locale={locale}
      showOutsideDays={showOutsideDays}
      className={cn("p-3 [--cell-size:--spacing(8)]", className)}
      classNames={{
        root: cn("w-fit", defaultClassNames.root),
        months: cn("relative flex flex-col gap-4 md:flex-row", defaultClassNames.months),
        month: cn("flex w-full flex-col gap-4", defaultClassNames.month),
        nav: cn(
          "absolute inset-x-0 top-0 flex w-full items-center justify-between gap-1",
          defaultClassNames.nav
        ),
        button_previous: cn(
          buttonVariants({ variant: "ghost" }),
          "size-(--cell-size) p-0 select-none aria-disabled:opacity-50",
          defaultClassNames.button_previous
        ),
        button_next: cn(
          buttonVariants({ variant: "ghost" }),
          "size-(--cell-size) p-0 select-none aria-disabled:opacity-50",
          defaultClassNames.button_next
        ),
        month_caption: cn(
          "flex h-(--cell-size) w-full items-center justify-center px-(--cell-size)",
          defaultClassNames.month_caption
        ),
        caption_label: cn("text-sm font-medium select-none", defaultClassNames.caption_label),
        month_grid: "w-full border-collapse",
        weekdays: cn("flex", defaultClassNames.weekdays),
        weekday: cn(
          "flex-1 text-label font-normal text-[color:var(--aqt-fg-faint)] select-none",
          defaultClassNames.weekday
        ),
        week: cn("mt-2 flex w-full", defaultClassNames.week),
        day: cn(
          "group/day relative aspect-square h-full w-full p-0 text-center select-none [&:first-child[data-selected=true]_button]:rounded-l-md [&:last-child[data-selected=true]_button]:rounded-r-md",
          defaultClassNames.day
        ),
        // The band a range's ends sit on, continued by its middle days.
        range_start: cn(
          "rounded-l-md bg-[color:var(--aqt-overlay-3)]",
          defaultClassNames.range_start
        ),
        range_middle: cn("rounded-none", defaultClassNames.range_middle),
        range_end: cn("rounded-r-md bg-[color:var(--aqt-overlay-3)]", defaultClassNames.range_end),
        today: cn("text-[color:var(--aqt-teal)]", defaultClassNames.today),
        outside: cn("text-[color:var(--aqt-fg-faint)]", defaultClassNames.outside),
        disabled: cn("text-[color:var(--aqt-fg-faint)] opacity-50", defaultClassNames.disabled),
        hidden: cn("invisible", defaultClassNames.hidden),
        ...classNames
      }}
      components={{
        Root: ({ className: rootClassName, rootRef, ...rootProps }) => (
          <div data-slot="calendar" ref={rootRef} className={rootClassName} {...rootProps} />
        ),
        // Only the month nav draws a chevron: no dropdown caption here.
        Chevron: ({ className: chevronClassName, orientation, ...chevronProps }) => {
          const Icon = orientation === "left" ? ChevronLeftIcon : ChevronRightIcon;
          return <Icon className={cn("size-4", chevronClassName)} {...chevronProps} />;
        },
        DayButton: CalendarDayButton,
        ...components
      }}
      {...props}
    />
  );
}

function CalendarDayButton({
  className,
  day,
  modifiers,
  ...props
}: React.ComponentProps<typeof DayButton>) {
  const defaultClassNames = getDefaultClassNames();

  const ref = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (modifiers.focused) ref.current?.focus();
  }, [modifiers.focused]);

  return (
    <Button
      ref={ref}
      // A chosen day (or a range's end) wears the teal tint of a chosen option, never a fill.
      variant={modifiers.selected && !modifiers.range_middle ? "accent" : "ghost"}
      size="icon"
      data-day={day.isoDate}
      data-range-middle={modifiers.range_middle}
      className={cn(
        "flex aspect-square size-auto w-full min-w-(--cell-size) flex-col gap-1 leading-none font-normal",
        "data-[range-middle=true]:rounded-none data-[range-middle=true]:bg-[color:var(--aqt-overlay-3)] data-[range-middle=true]:text-[color:var(--aqt-fg)]",
        defaultClassNames.day,
        className
      )}
      {...props}
    />
  );
}

export { Calendar };
