"use client";

import * as React from "react";
import { ChevronDownIcon, X } from "lucide-react";
import { type DateTimeFormatOptions, useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { Button, selectTriggerClass, triggerChevronClass } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Field, FieldLabel } from "@/components/ui/field";
import { TimeInput } from "@/components/ui/time-input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * The slice of next-intl's formatter these triggers need. `useFormatter()` and
 * `await getFormatter()` both satisfy it, so the helpers below never have to pin
 * a locale of their own.
 */
interface DateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

interface DateTimePickerProps {
  clearLabel?: string;
  dateLabel?: string;
  disabled?: boolean;
  id?: string;
  minDate?: Date;
  onChange: (value: string) => void;
  placeholder?: string;
  timeLabel?: string;
  timeId?: string;
  value?: string | null;
  /**
   * Extra classes for the two field labels — pass `lg:sr-only` to hide them
   * visually above a breakpoint while keeping them for assistive tech. For a
   * grid of pickers where one header row already names the columns: repeating
   * "Starts at / Time" on every row is noise on screen, but it is the only
   * accessible name each control has.
   */
  labelClassName?: string;
  /** `sm` is the 32px toolbar row, `default` the 36px form row; the time field follows. */
  size?: "sm" | "default";
  /** The date trigger's surface; `surface` is the public form skin. */
  variant?: "default" | "surface";
}

/**
 * Calendar fields of a local-time Date, re-anchored to UTC.
 *
 * The trigger below prints a calendar day, but the app formatter carries the
 * zone the SERVER rendered in — the viewer's once their browser has reported
 * it, the workspace default before that — not necessarily the browser's own.
 * Formatting these Dates raw (a local wall clock from `parseDateTimeValue`)
 * could print the neighbouring day,
 * disagreeing with the highlighted calendar cell and with the adjacent
 * `TimeInput`, which reads local hours.
 */
function calendarDayInUtc(date: Date): Date {
  return new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
}

/**
 * Date part only — the `DateTimePicker` puts the clock in its own adjacent
 * `TimeInput`. Pre-existing behaviour, preserved verbatim; flagged rather than
 * "fixed", since changing it would alter every trigger's rendered text.
 */
function formatDateTimeDisplay(format: DateFormatter, date: Date | undefined): string {
  if (!date) return "";
  return format.dateTime(calendarDayInUtc(date), {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC"
  });
}

function parseDateTimeValue(value?: string | null): Date | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

function toLocalDateTime(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function getTimeValue(date: Date | undefined): string {
  if (!date) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function withTime(date: Date, timeValue: string): Date {
  const [hours = "12", minutes = "00", seconds = "00"] = timeValue.split(":");
  const next = new Date(date);
  next.setHours(Number(hours), Number(minutes), Number(seconds), 0);
  return next;
}

function isBeforeMinDate(date: Date, minDate: Date | undefined): boolean {
  if (!minDate) return false;
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const min = new Date(minDate);
  min.setHours(0, 0, 0, 0);
  return target < min;
}

export function DateTimePicker({
  clearLabel,
  dateLabel,
  disabled = false,
  id,
  minDate,
  onChange,
  placeholder,
  timeLabel,
  timeId,
  value,
  labelClassName,
  size,
  variant
}: Readonly<DateTimePickerProps>) {
  const t = useTranslations("kit.datePicker");
  const format = useFormatter();
  const [open, setOpen] = React.useState(false);
  const selected = React.useMemo(() => parseDateTimeValue(value), [value]);
  const timeValue = getTimeValue(selected);

  return (
    <div className="flex items-end gap-2 w-full">
      <div className="flex flex-1 flex-col gap-2 sm:flex-row min-w-0">
        <Field className="min-w-0 flex-1 gap-1.5" data-disabled={disabled}>
          <FieldLabel htmlFor={id} className={labelClassName}>
            {dateLabel ?? t("date")}
          </FieldLabel>
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <button
                id={id}
                type="button"
                data-placeholder={selected ? undefined : ""}
                disabled={disabled}
                className={selectTriggerClass(size, variant)}
              >
                <span>
                  {selected
                    ? formatDateTimeDisplay(format, selected)
                    : (placeholder ?? t("select"))}
                </span>
                <ChevronDownIcon aria-hidden className={triggerChevronClass} />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-auto overflow-hidden p-0" align="start">
              <Calendar
                mode="single"
                selected={selected}
                defaultMonth={selected}
                disabled={(date) => isBeforeMinDate(date, minDate)}
                onSelect={(date) => {
                  if (!date) {
                    onChange("");
                    setOpen(false);
                    return;
                  }
                  onChange(toLocalDateTime(withTime(date, timeValue || "12:00")));
                  setOpen(false);
                }}
              />
            </PopoverContent>
          </Popover>
        </Field>
        <Field className="gap-1.5 sm:w-32 sm:shrink-0" data-disabled={disabled}>
          <FieldLabel htmlFor={timeId} className={labelClassName}>
            {timeLabel ?? t("time")}
          </FieldLabel>
          <TimeInput
            id={timeId}
            value={timeValue}
            disabled={disabled}
            size={size}
            onValueChange={(nextTime) => {
              const baseDate = selected ?? new Date();
              onChange(toLocalDateTime(withTime(baseDate, nextTime || "12:00")));
            }}
          />
        </Field>
      </div>
      {selected && !disabled ? (
        <Button
          type="button"
          variant="ghost-destructive"
          size={size === "sm" ? "icon-toolbar" : "icon"}
          className="shrink-0"
          onClick={() => onChange("")}
          aria-label={clearLabel ?? t("clear")}
          title={clearLabel ?? t("clear")}
        >
          <X className="size-4" />
        </Button>
      ) : null}
    </div>
  );
}
