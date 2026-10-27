"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { type DateTimeFormatOptions, useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { type DateRange } from "react-day-picker";

import { selectTriggerClass, triggerChevronClass } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * The slice of next-intl's formatter this trigger needs. `useFormatter()` and
 * `await getFormatter()` both satisfy it, so `formatDisplay` never has to pin a
 * locale of its own.
 */
interface DateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

interface DateRangePickerProps {
  startDate?: string;
  endDate?: string;
  onChange: (startDate: string, endDate: string) => void;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  /** `sm` is the 32px toolbar row, `default` the 36px form row. */
  size?: "sm" | "default";
  /** `surface` is the public form skin. */
  variant?: "default" | "surface";
}

/**
 * The Dates here are LOCAL midnight (`parseDateValue`), but the app formatter
 * carries the zone the SERVER rendered in — the viewer's once their browser has
 * reported it, the workspace default before that — which need not be the zone
 * this Date was built in. Formatting a local-midnight Date through a zone west
 * of the browser's printed the previous day: the calendar highlighted 12-13 Sep
 * while the trigger read "11 сент. - 12 сент.". Re-anchor the calendar fields
 * to UTC and name the zone, so the label always matches the highlighted cell
 * and the ISO value sent up, in every zone and identically on server and client.
 */
function formatDisplay(format: DateFormatter, date: Date): string {
  return format.dateTime(new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())), {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC"
  });
}

function parseDateValue(value?: string): Date | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DateRangePicker({
  startDate,
  endDate,
  onChange,
  placeholder,
  id,
  disabled,
  size,
  variant
}: Readonly<DateRangePickerProps>) {
  const t = useTranslations("kit.datePicker");
  const format = useFormatter();
  const [open, setOpen] = React.useState(false);

  const from = React.useMemo(() => parseDateValue(startDate), [startDate]);
  const to = React.useMemo(() => parseDateValue(endDate), [endDate]);

  const selected: DateRange | undefined = from || to ? { from, to } : undefined;

  const displayText = React.useMemo(() => {
    if (from && to) return `${formatDisplay(format, from)} - ${formatDisplay(format, to)}`;
    if (from) return formatDisplay(format, from);
    return "";
  }, [format, from, to]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          data-placeholder={from ? undefined : ""}
          disabled={disabled}
          className={selectTriggerClass(size, variant)}
        >
          <span>{displayText || (placeholder ?? t("pickRange"))}</span>
          <ChevronDown aria-hidden className={triggerChevronClass} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto overflow-hidden p-0" align="start">
        <Calendar
          mode="range"
          defaultMonth={from}
          selected={selected}
          onSelect={(range) => {
            onChange(
              range?.from ? toIsoDate(range.from) : "",
              range?.to ? toIsoDate(range.to) : ""
            );
          }}
          numberOfMonths={2}
        />
      </PopoverContent>
    </Popover>
  );
}
