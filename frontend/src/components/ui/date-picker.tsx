"use client";

import * as React from "react";
import { CalendarIcon, ChevronDownIcon, X } from "lucide-react";
import { type DateTimeFormatOptions } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
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

interface DatePickerProps {
  value?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  id?: string;
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
}

/**
 * Calendar fields of a local-time Date, re-anchored to UTC.
 *
 * The triggers below print a calendar day, but the app formatter carries the
 * zone the SERVER rendered in — the viewer's once their browser has reported
 * it, the workspace default before that — not necessarily the browser's own.
 * Formatting these Dates raw (local midnight from `parseDateValue`, or a local
 * wall clock from `parseDateTimeValue`) could print the neighbouring day,
 * disagreeing with the highlighted calendar cell and with the adjacent
 * `TimeInput`, which reads local hours.
 */
function calendarDayInUtc(date: Date): Date {
  return new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
}

/**
 * Takes the formatter rather than pinning a locale: an `en-US` literal here
 * printed English dates into the `ru` default UI. Callers pass `useFormatter()`.
 */
function formatDisplay(format: DateFormatter, date: Date | undefined): string {
  if (!date) return "";
  return format.dateTime(calendarDayInUtc(date), {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC"
  });
}

/**
 * NOTE: identical to `formatDisplay` — the date-and-time trigger shows only the
 * date part. Pre-existing behaviour, preserved verbatim; the `DateTimePicker`
 * puts the clock in its own adjacent `TimeInput`, so this may well be
 * intentional. Flagged rather than "fixed", since changing it would alter every
 * `DateTimePicker` trigger's rendered text.
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

function parseDateValue(value?: string): Date | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

function parseDateTimeValue(value?: string | null): Date | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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

export function DatePicker({ value, onChange, placeholder = "Pick a date", id }: Readonly<DatePickerProps>) {
  const format = useFormatter();
  const [open, setOpen] = React.useState(false);
  const selected = React.useMemo(() => parseDateValue(value), [value]);

  const currentYear = new Date().getFullYear();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          data-empty={!selected}
          className={cn(
            "w-full justify-start text-left font-normal",
            "data-[empty=true]:text-muted-foreground"
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {selected ? formatDisplay(format, selected) : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          captionLayout="dropdown"
          selected={selected}
          defaultMonth={selected}
          onSelect={(date) => {
            if (date) {
              onChange(toIsoDate(date));
            } else {
              onChange("");
            }
            setOpen(false);
          }}
          startMonth={new Date(currentYear - 10, 0)}
          endMonth={new Date(currentYear + 10, 11)}
        />
      </PopoverContent>
    </Popover>
  );
}

export function DateTimePicker({
  clearLabel = "Clear",
  dateLabel = "Date",
  disabled = false,
  id,
  minDate,
  onChange,
  placeholder = "Select date",
  timeLabel = "Time",
  timeId,
  value,
  labelClassName
}: Readonly<DateTimePickerProps>) {
  const format = useFormatter();
  const [open, setOpen] = React.useState(false);
  const selected = React.useMemo(() => parseDateTimeValue(value), [value]);
  const timeValue = getTimeValue(selected);

  return (
    <div className="flex items-end gap-2 w-full">
      <div className="flex flex-1 flex-col gap-2 sm:flex-row min-w-0">
        <Field className="min-w-0 flex-1 gap-1.5" data-disabled={disabled}>
          <FieldLabel htmlFor={id} className={labelClassName}>
            {dateLabel}
          </FieldLabel>
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <Button
                id={id}
                type="button"
                variant="outline"
                data-empty={!selected}
                disabled={disabled}
                className={cn(
                  "w-full justify-between font-normal",
                  "data-[empty=true]:text-muted-foreground"
                )}
              >
                <span className="truncate">
                  {selected ? formatDateTimeDisplay(format, selected) : placeholder}
                </span>
                <ChevronDownIcon data-icon="inline-end" />
              </Button>
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
            {timeLabel}
          </FieldLabel>
          <TimeInput
            id={timeId}
            value={timeValue}
            disabled={disabled}
            className="bg-background"
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
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          onClick={() => onChange("")}
          title={clearLabel}
        >
          <X className="size-4" />
        </Button>
      ) : null}
    </div>
  );
}
