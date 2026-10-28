"use client";

import { Fragment } from "react";
import { Save, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
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
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import type {
  BalancerConfig,
  BalancerConfigField,
  BalancerConfigValue,
  BalancerRoleSettings,
} from "@/types/balancer.types";

/** Drawer sections in order, each with its `config.groups.*` message. */
const GROUPS = [
  ["Algorithm", "algorithm"],
  ["Quality weights", "qualityWeights"],
  ["Strategy", "strategy"],
  ["Solver output", "solverOutput"],
] as const satisfies ReadonlyArray<readonly [BalancerConfigField["group"], string]>;

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
  /** The tournament owner's role dictionary: the names the role rows are labelled with. */
  ontology?: RoleOntology | null;
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

/** A knob's or a role column's catalog copy, keyed like the server row; one the
 * catalog does not know yet keeps the server's own English. */
function useKnobCopy() {
  const t = useTranslations("balancerTool.playerEdit.config");
  return (kind: "fields" | "columns", key: string, part: "label" | "description", fallback: string) => {
    const id = `${kind}.${key}.${part}` as "fields.population_size.label";
    return t.has(id) ? t(id) : fallback;
  };
}

/** Role rows in the roster vocabulary's order, anything newer appended as it
 * came. The roster shape decides WHICH roles get a row; without one, every
 * role the backend declares in its `role_settings` default does. A role left
 * out still keeps whatever this tournament stored for it -- the table only
 * stops showing it, it never rewrites it. */
function roleRowOrder(defaults: BalancerRoleSettings, roleCodes?: string[] | null): string[] {
  return Object.keys(defaults).filter((code) => roleCodes == null || roleCodes.includes(code));
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
  ontology,
  onChange,
}: Readonly<{
  field: BalancerConfigField;
  value: BalancerConfigValue;
  roleCodes?: string[] | null;
  ontology?: RoleOntology | null;
  onChange: (value: BalancerConfigValue) => void;
}>) {
  const slotLabel = useSlotLabel(ontology);
  const knobCopy = useKnobCopy();
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
        <Eyebrow
          as="div"
          key={column.key}
          title={knobCopy("columns", column.key, "description", column.description)}
          tone="dim"
          className="text-center"
        >
          {knobCopy("columns", column.key, "label", column.label)}
        </Eyebrow>
      ))}
      {roles.map((role) => (
        <Fragment key={role}>
          <div className="self-center text-sm text-[color:var(--aqt-fg)]">
            {slotLabel(role)}
          </div>
          {columns.map((column) => (
            <NumberInput
              key={column.key}
              id={`config-${field.key}-${role}-${column.key}`}
              aria-label={`${role} ${knobCopy("columns", column.key, "label", column.label)}`}
              value={overrides[role]?.[column.key] ?? defaults[role]?.[column.key] ?? null}
              onValueChange={(next) => setCell(role, column.key, next)}
              min={column.limits?.min}
              max={column.limits?.max}
              className="text-center"
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
  ontology,
  onChange,
}: Readonly<{
  field: BalancerConfigField;
  value: BalancerConfigValue;
  roleCodes?: string[] | null;
  ontology?: RoleOntology | null;
  onChange: (value: BalancerConfigValue) => void;
}>) {
  const t = useTranslations("balancerTool.playerEdit.config");
  if (field.type === "boolean") {
    return <Switch id={`config-${field.key}`} checked={Boolean(value)} onCheckedChange={onChange} />;
  }

  if (field.type === "roles") {
    return (
      <ConfigRolesTable field={field} value={value} roleCodes={roleCodes} ontology={ontology} onChange={onChange} />
    );
  }

  if (field.type === "open_slot") {
    return (
      <ConfigRolesTable
        field={{ ...field, default: { flex: field.default as Record<string, number> } }}
        value={value == null ? null : ({ flex: value } as BalancerConfigValue)}
        roleCodes={null}
        ontology={ontology}
        onChange={(next) => onChange((next as BalancerRoleSettings | undefined)?.flex ?? null)}
      />
    );
  }

  // No `select`/`role_mask` branches: the backend emits only
  // boolean/integer/float/slider/roles/open_slot rows. `algorithm` died with the
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
          aria-labelledby={`config-${field.key}-label`}
          min={min}
          max={max}
          step={0.05}
          value={[numeric]}
          onValueChange={(next) => onChange(next[0])}
        />
        <div className="flex justify-between text-label text-[color:var(--aqt-fg-dim)]">
          <span>{t("balance")}</span>
          <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">{numeric.toFixed(2)}</span>
          <span>{t("comfort")}</span>
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
  ontology,
}: Readonly<BalancerConfigDrawerProps>) {
  const t = useTranslations("balancerTool.playerEdit.config");
  const tCommon = useTranslations("common");
  const knobCopy = useKnobCopy();
  const fieldsByGroup = GROUPS.map(([group, labelKey]) => ({
    group,
    labelKey,
    fields: fields.filter((field) => field.group === group),
  })).filter((item) => item.fields.length > 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent variant="panel" className="w-full sm:max-w-2xl">
        <SheetHeader variant="panel">
          <SheetTitle>{t("title")}</SheetTitle>
          <SheetDescription>{t("description", { preset: selectedPresetLabel })}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-5">
            {fieldsByGroup.map(({ group, labelKey, fields: groupFields }) => (
              <section key={group} className="space-y-3">
                <Eyebrow as="div" tone="dim">
                  {t(`groups.${labelKey}`)}
                </Eyebrow>
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
                            field.type === "roles" || field.type === "open_slot"
                              ? "grid gap-3"
                              : "grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]"
                          }
                        >
                          <div>
                            <Label
                              id={`config-${field.key}-label`}
                              htmlFor={field.type === "roles" || field.type === "open_slot" ? undefined : `config-${field.key}`}
                              className="text-sm text-[color:var(--aqt-fg)]"
                            >
                              {knobCopy("fields", field.key, "label", field.label)}
                            </Label>
                            <p className="mt-1 text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
                              {knobCopy("fields", field.key, "description", field.description)}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2 text-label text-[color:var(--aqt-fg-dim)]">
                              {/* A roles table shows its own defaults in the
                                  cells; dumping the whole dict here is noise. */}
                              {field.type === "roles" || field.type === "open_slot" ? null : (
                                <span>{t("default", { value: formatValue(field.default) })}</span>
                              )}
                              {field.limits ? (
                                <span>
                                  {t("limit", { min: String(field.limits.min), max: String(field.limits.max) })}
                                </span>
                              ) : null}
                            </div>
                          </div>
                          <div>
                            <ConfigFieldControl
                              field={field}
                              value={value}
                              roleCodes={roleCodes}
                              ontology={ontology}
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

        <SheetFooter variant="panel">
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-[color:var(--aqt-fg-dim)]">
              {dirty ? t("unsaved") : t("saved")}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={onReset}
                className="rounded-lg"
              >
                <RotateCcw className="mr-2 h-4 w-4" />
                {tCommon("reset")}
              </Button>
              <Button type="button" onClick={onSave} disabled={!dirty || saving} className="rounded-lg">
                <Save className="mr-2 h-4 w-4" />
                {t("save")}
              </Button>
            </div>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
