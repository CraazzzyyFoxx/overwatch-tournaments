"use client";

import { Save, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import type {
  BalancerConfig,
  BalancerConfigField,
  BalancerConfigValue,
} from "@/types/balancer.types";

const GROUP_ORDER: BalancerConfigField["group"][] = [
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
  onChange: (key: string, value: BalancerConfigValue) => void;
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

function ConfigFieldControl({
  field,
  value,
  onChange,
}: Readonly<{
  field: BalancerConfigField;
  value: BalancerConfigValue;
  onChange: (value: BalancerConfigValue) => void;
}>) {
  if (field.type === "boolean") {
    return <Switch checked={Boolean(value)} onCheckedChange={onChange} />;
  }

  // No `select`/`role_mask` branches: the backend emits only
  // boolean/integer/float/slider rows. `algorithm` died with the pure-Python
  // solver, and the per-team slot counts come from the tournament roster shape
  // rather than from this drawer.
  if (field.type === "slider") {
    const numeric =
      typeof value === "number" ? value : Number(value ?? field.default ?? 0);
    const min = field.limits?.min ?? 0;
    const max = field.limits?.max ?? 1;
    return (
      <div className="flex flex-col gap-2">
        <Slider
          min={min}
          max={max}
          step={0.05}
          value={[numeric]}
          onValueChange={(next) => onChange(next[0])}
        />
        <div className="flex justify-between text-label text-[color:var(--aqt-fg-dim)]">
          <span>balance</span>
          <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">{numeric.toFixed(2)}</span>
          <span>comfort</span>
        </div>
      </div>
    );
  }

  const numericValue =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))
        ? Number(value)
        : null;

  return (
    <NumberInput
      id={`config-${field.key}`}
      value={numericValue}
      onValueChange={onChange}
      min={field.limits?.min}
      max={field.limits?.max}
      integer={field.type === "integer"}
      className="h-9 rounded-lg"
    />
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
}: Readonly<BalancerConfigDrawerProps>) {
  const fieldsByGroup = GROUP_ORDER.map((group) => ({
    group,
    fields: fields.filter((field) => field.group === group),
  })).filter((item) => item.fields.length > 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-hidden border-border bg-popover p-0 text-[color:var(--aqt-fg)] sm:max-w-2xl">
        <SheetHeader className="border-b border-[color:var(--aqt-border-2)] px-5 py-4">
          <SheetTitle className="text-[color:var(--aqt-fg)]">Balancer settings</SheetTitle>
          <SheetDescription className="text-[color:var(--aqt-fg-muted)]">
            Active preset: {selectedPresetLabel}. Changes are saved for this tournament.
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-5">
            {fieldsByGroup.map(({ group, fields: groupFields }) => (
              <section key={group} className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  {group}
                </div>
                <div className="space-y-3">
                  {groupFields.map((field) => {
                    const value = config[field.key] ?? field.default;
                    return (
                      <div
                        key={field.key}
                        className="rounded-lg border border-[color:var(--aqt-border-2)] bg-black/15 p-3"
                      >
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
                          <div>
                            <Label htmlFor={`config-${field.key}`} className="text-sm text-[color:var(--aqt-fg)]">
                              {field.label}
                            </Label>
                            <p className="mt-1 text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
                              {field.description}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2 text-label text-[color:var(--aqt-fg-dim)]">
                              <span>Default: {formatValue(field.default)}</span>
                              {field.limits ? (
                                <span>
                                  Limit: {field.limits.min} - {field.limits.max}
                                </span>
                              ) : null}
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

        <SheetFooter className="border-t border-[color:var(--aqt-border-2)] px-5 py-4">
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-[color:var(--aqt-fg-dim)]">
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
