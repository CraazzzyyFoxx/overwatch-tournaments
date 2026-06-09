"use client";

import { useEffect, useState } from "react";
import { Save, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import type { BalancerConfig, BalancerConfigField } from "@/types/balancer.types";

const GROUP_ORDER: BalancerConfigField["group"][] = [
  "Roles",
  "Algorithm",
  "Quality weights",
  "Strategy",
  "Solver output",
];

type BalancerConfigDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fields: BalancerConfigField[];
  config: BalancerConfig;
  selectedPresetLabel: string;
  dirty: boolean;
  saving: boolean;
  onChange: (key: keyof BalancerConfig, value: unknown) => void;
  onSave: () => void;
  onReset: () => void;
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

function normalizeNumericText(value: string, field: BalancerConfigField): string | null {
  const normalized = value.replace(",", ".");
  const pattern = field.type === "integer" ? /^\d*$/ : /^\d*(?:\.\d*)?$/;

  return pattern.test(normalized) ? normalized : null;
}

function clampNumber(value: number, field: BalancerConfigField): number {
  const min = field.limits?.min;
  const max = field.limits?.max;
  let nextValue = field.type === "integer" ? Math.round(value) : value;

  if (typeof min === "number" && nextValue < min) {
    nextValue = min;
  }
  if (typeof max === "number" && nextValue > max) {
    nextValue = max;
  }

  return nextValue;
}

function NumericConfigInput({
  field,
  value,
  onChange,
}: {
  field: BalancerConfigField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [rawValue, setRawValue] = useState(() =>
    value === undefined || value === null ? "" : String(value)
  );
  const [isFocused, setIsFocused] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect -- Keep the editable string in sync with preset/reset changes while preserving in-progress typing. */
  useEffect(() => {
    if (!isFocused) {
      setRawValue(value === undefined || value === null ? "" : String(value));
    }
  }, [isFocused, value]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleChange = (nextRawValue: string) => {
    const normalized = normalizeNumericText(nextRawValue, field);
    if (normalized === null) {
      return;
    }

    setRawValue(normalized);

    if (normalized === "" || normalized === ".") {
      onChange("");
      return;
    }

    if (normalized.endsWith(".")) {
      onChange(normalized);
      return;
    }

    onChange(Number(normalized));
  };

  const handleBlur = () => {
    setIsFocused(false);
    if (rawValue === "" || rawValue === ".") {
      onChange("");
      return;
    }

    const numericValue = Number(rawValue);
    if (!Number.isFinite(numericValue)) {
      return;
    }

    const clampedValue = clampNumber(numericValue, field);
    setRawValue(String(clampedValue));
    onChange(clampedValue);
  };

  return (
    <Input
      id={`config-${field.key}`}
      value={rawValue}
      type="text"
      inputMode={field.type === "integer" ? "numeric" : "decimal"}
      onFocus={() => setIsFocused(true)}
      onBlur={handleBlur}
      onChange={(event) => handleChange(event.target.value)}
      className="h-9 rounded-lg"
    />
  );
}

function ConfigMapEditor({
  id,
  value,
  valueType,
  onChange,
}: {
  id: string;
  value: Record<string, number | string>;
  valueType: "number" | "string";
  onChange: (value: Record<string, number | string>) => void;
}) {
  const entries = Object.entries(value);
  const nextKeyPrefix = valueType === "number" ? "Role" : "role";
  const nextKey =
    entries.length === 0
      ? nextKeyPrefix
      : `${nextKeyPrefix}_${entries.length + 1}`;

  const updateEntry = (index: number, nextKey: string, nextValue: string) => {
    const nextEntries = entries.map(([key, currentValue], entryIndex) => {
      if (entryIndex !== index) {
        return [key, currentValue] as const;
      }

      return [
        nextKey,
        valueType === "number" ? Number(nextValue || 0) : nextValue,
      ] as const;
    });
    onChange(Object.fromEntries(nextEntries));
  };

  const removeEntry = (index: number) => {
    onChange(Object.fromEntries(entries.filter((_, entryIndex) => entryIndex !== index)));
  };

  return (
    <div id={id} className="space-y-2">
      {entries.map(([key, currentValue], index) => (
        <div key={`${key}-${index}`} className="grid grid-cols-[1fr_1fr_auto] gap-2">
          <Input
            value={key}
            onChange={(event) => updateEntry(index, event.target.value, String(currentValue))}
            className="h-8 rounded-lg"
            aria-label="Config key"
          />
          <Input
            value={String(currentValue)}
            type={valueType}
            onChange={(event) => updateEntry(index, key, event.target.value)}
            className="h-8 rounded-lg"
            aria-label="Config value"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => removeEntry(index)}
            className="h-8 rounded-lg"
          >
            Remove
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange({ ...value, [nextKey]: valueType === "number" ? 0 : "" })}
        className="h-8 rounded-lg"
      >
        Add row
      </Button>
    </div>
  );
}

function ConfigFieldControl({
  field,
  value,
  onChange,
}: {
  field: BalancerConfigField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  if (field.type === "boolean") {
    return <Switch checked={Boolean(value)} onCheckedChange={onChange} />;
  }

  if (field.type === "select") {
    return (
      <Select value={String(value ?? "")} onValueChange={onChange}>
        <SelectTrigger className="h-9 rounded-lg">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(field.options ?? []).map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (field.type === "role_mask") {
    return (
      <ConfigMapEditor
        id={`config-${field.key}`}
        value={(value as Record<string, number | string> | undefined) ?? {}}
        valueType="number"
        onChange={onChange}
      />
    );
  }

  return (
    <NumericConfigInput field={field} value={value} onChange={onChange} />
  );
}

export function BalancerConfigDrawer({
  open,
  onOpenChange,
  fields,
  config,
  selectedPresetLabel,
  dirty,
  saving,
  onChange,
  onSave,
  onReset,
}: BalancerConfigDrawerProps) {
  const fieldsByGroup = GROUP_ORDER.map((group) => ({
    group,
    fields: fields.filter((field) => field.group === group),
  })).filter((item) => item.fields.length > 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-hidden border-border bg-popover p-0 text-white sm:max-w-2xl">
        <SheetHeader className="border-b border-white/10 px-5 py-4">
          <SheetTitle className="text-white">Balancer settings</SheetTitle>
          <SheetDescription className="text-white/52">
            Active preset: {selectedPresetLabel}. Changes are saved for this tournament.
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-5">
            {fieldsByGroup.map(({ group, fields: groupFields }) => (
              <section key={group} className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-white/40">
                  {group}
                </div>
                <div className="space-y-3">
                  {groupFields.map((field) => {
                    const value = config[field.key] ?? field.default;
                    return (
                      <div
                        key={field.key}
                        className="rounded-lg border border-white/10 bg-black/15 p-3"
                      >
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
                          <div>
                            <Label htmlFor={`config-${field.key}`} className="text-sm text-white/90">
                              {field.label}
                            </Label>
                            <p className="mt-1 text-xs leading-5 text-white/48">
                              {field.description}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-white/35">
                              <span>Default: {formatValue(field.default)}</span>
                              {field.limits ? (
                                <span>
                                  Limit: {field.limits.min} - {field.limits.max}
                                </span>
                              ) : null}
                              <span>Applies: {field.applies_to.join(", ")}</span>
                            </div>
                          </div>
                          <div>
                            <ConfigFieldControl
                              field={field}
                              value={value}
                              onChange={(nextValue) => onChange(field.key, nextValue)}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </div>

        <SheetFooter className="border-t border-white/10 px-5 py-4">
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-white/42">
              {dirty ? "Unsaved settings will be saved before the next run." : "Settings are saved."}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={onReset}
                className="rounded-lg"
              >
                <RotateCcw className="mr-2 h-4 w-4" />
                Reset
              </Button>
              <Button type="button" onClick={onSave} disabled={!dirty || saving} className="rounded-lg">
                <Save className="mr-2 h-4 w-4" />
                Save settings
              </Button>
            </div>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
