"use client";

import { Fragment } from "react";
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
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { ROSTER_SLOT_CODES, isRosterSlotCode } from "@/lib/roster/shape";
import type {
  BalancerConfig,
  BalancerConfigField,
  BalancerConfigValue,
  BalancerRoleSettings,
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
  /** Slot codes of the tournament's roster shape: the roles a `roles` table
   *  offers a row for. `null` until the shape is known -- then every role the
   *  backend declares gets a row, which is also what a shapeless run uses. */
  roleCodes?: string[] | null;
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

/** Role rows in the roster vocabulary's order, anything newer appended as it
 * came. The roster shape decides WHICH roles get a row; without one, every
 * role the backend declares in its `role_settings` default does. A role left
 * out still keeps whatever this tournament stored for it -- the table only
 * stops showing it, it never rewrites it. */
function roleRowOrder(defaults: BalancerRoleSettings, roleCodes?: string[] | null): string[] {
  const codes = Object.keys(defaults).filter(
    (code) => roleCodes == null || roleCodes.includes(code)
  );
  return [
    ...ROSTER_SLOT_CODES.filter((code) => codes.includes(code)),
    ...codes.filter((code) => !isRosterSlotCode(code)),
  ];
}

/** Only the cells moved off their default travel. The server merges a stored
 * row field by field over its own defaults, so sending back a full copy would
 * pin today's numbers to this tournament forever. */
function minimalRoleOverrides(
  value: BalancerRoleSettings,
  defaults: BalancerRoleSettings
): BalancerRoleSettings | undefined {
  const overrides: BalancerRoleSettings = {};

  for (const [role, row] of Object.entries(value)) {
    const changed = Object.fromEntries(
      Object.entries(row ?? {}).filter(
        ([column, cell]) => typeof cell === "number" && cell !== defaults[role]?.[column]
      )
    );
    if (Object.keys(changed).length > 0) {
      overrides[role] = changed;
    }
  }

  return Object.keys(overrides).length > 0 ? overrides : undefined;
}

/** One row per role, one numeric input per declared column. An empty cell is
 * not an empty value: it falls back to the role's default, which is also what
 * clearing one means. */
function ConfigRolesTable({
  field,
  value,
  roleCodes,
  onChange,
}: Readonly<{
  field: BalancerConfigField;
  value: BalancerConfigValue;
  roleCodes?: string[] | null;
  onChange: (value: BalancerConfigValue) => void;
}>) {
  const defaults = (field.default ?? {}) as BalancerRoleSettings;
  const overrides = (value ?? {}) as BalancerRoleSettings;
  const columns = field.columns ?? [];
  const roles = roleRowOrder(defaults, roleCodes);

  const setCell = (role: string, column: string, next: number | null) => {
    const merged = {
      ...overrides,
      [role]: { ...overrides[role], [column]: next ?? defaults[role]?.[column] },
    };
    onChange(minimalRoleOverrides(merged, defaults));
  };

  return (
    <div
      className="grid gap-2"
      style={{ gridTemplateColumns: `minmax(0,1fr) repeat(${columns.length}, 96px)` }}
    >
      <div />
      {columns.map((column) => (
        <div
          key={column.key}
          title={column.description}
          className="text-center text-label uppercase tracking-label text-[color:var(--aqt-fg-dim)]"
        >
          {column.label}
        </div>
      ))}
      {roles.map((role) => (
        <Fragment key={role}>
          <div className="self-center text-sm text-[color:var(--aqt-fg)]">
            {isRosterSlotCode(role) ? normalizePlayerRole(role) : role}
          </div>
          {columns.map((column) => (
            <NumberInput
              key={column.key}
              id={`config-${field.key}-${role}-${column.key}`}
              aria-label={`${role} ${column.label}`}
              value={overrides[role]?.[column.key] ?? defaults[role]?.[column.key] ?? null}
              onValueChange={(next) => setCell(role, column.key, next)}
              min={column.limits?.min}
              max={column.limits?.max}
              className="h-9 rounded-lg px-2 text-center tabular-nums"
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
}

function ConfigFieldControl({
  field,
  value,
  roleCodes,
  onChange,
}: Readonly<{
  field: BalancerConfigField;
  value: BalancerConfigValue;
  roleCodes?: string[] | null;
  onChange: (value: BalancerConfigValue) => void;
}>) {
  if (field.type === "boolean") {
    return <Switch checked={Boolean(value)} onCheckedChange={onChange} />;
  }

  if (field.type === "roles") {
    return (
      <ConfigRolesTable field={field} value={value} roleCodes={roleCodes} onChange={onChange} />
    );
  }

  // No `select`/`role_mask` branches: the backend emits only
  // boolean/integer/float/slider/roles rows. `algorithm` died with the
  // pure-Python solver, and the per-team slot counts come from the tournament
  // roster shape rather than from this drawer.
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
  roleCodes,
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
                <div className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  {group}
                </div>
                <div className="space-y-3">
                  {groupFields.map((field) => {
                    const value = config[field.key] ?? field.default;
                    return (
                      <div
                        key={field.key}
                        className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] p-3"
                      >
                        <div
                          className={
                            // The table is as wide as it has columns; a knob
                            // with one input keeps the narrow control column.
                            field.type === "roles"
                              ? "grid gap-3"
                              : "grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]"
                          }
                        >
                          <div>
                            <Label
                              htmlFor={field.type === "roles" ? undefined : `config-${field.key}`}
                              className="text-sm text-[color:var(--aqt-fg)]"
                            >
                              {field.label}
                            </Label>
                            <p className="mt-1 text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
                              {field.description}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2 text-label text-[color:var(--aqt-fg-dim)]">
                              {/* A roles table shows its own defaults in the
                                  cells; dumping the whole dict here is noise. */}
                              {field.type === "roles" ? null : (
                                <span>Default: {formatValue(field.default)}</span>
                              )}
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
                              roleCodes={roleCodes}
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
