"use client";

import { Minus, Plus, Sprout, Trash2 } from "lucide-react";

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
import type { ValueMapRow } from "@/types/balancer-admin.types";
import type { SubroleCatalog, SubroleOption } from "@/types/registration.types";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { registrationRoles, type RoleOntology } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import { useTranslations } from "next-intl";

type ValueEditorKind = "boolean" | "role" | "text" | "number" | "role_subrole" | "subrole";

interface ValueMapEditorProps {
  title: string;
  description: string;
  kind: ValueEditorKind;
  rows: ValueMapRow[];
  /** Whether catalog defaults are available to seed. */
  canSeed: boolean;
  subroleCatalog?: SubroleCatalog;
  /** The tournament's game: the roles a sheet's text can map to. Only the role editors read it; `null` while it loads (no role is offered). */
  ontology?: RoleOntology | null;
  onAdd: () => void;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
  onRemove: (id: string) => void;
  onSeedDefaults: () => void;
}

const NONE = "__none__";

function optionsForRole(catalog: SubroleCatalog | undefined, role: string): SubroleOption[] {
  if (!role || role === OPEN_SLOT_CODE) return [];
  return catalog?.[role] ?? [];
}

function flattenSubroleOptions(catalog: SubroleCatalog | undefined): { value: string; label: string }[] {
  const bySlug = new Map<string, { label: string; roles: string[] }>();
  for (const [role, options] of Object.entries(catalog ?? {})) {
    for (const option of options) {
      const existing = bySlug.get(option.slug);
      if (existing) existing.roles.push(role);
      else bySlug.set(option.slug, { label: option.label, roles: [role] });
    }
  }
  return [...bySlug.entries()].map(([slug, { label, roles }]) => ({
    value: slug,
    label: roles.length > 1 ? `${label} (${roles.join(", ")})` : label,
  }));
}

const BOOLEAN_OPTIONS = [
  { value: "true", label: "true" },
  { value: "false", label: "false" },
] as const;

type RoleSubroleItem = { role: string; subrole: string | null };

function parseRoleSubroleItems(value: string): RoleSubroleItem[] {
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed)) {
      const items = parsed.map((e) =>
        e && typeof e === "object" && typeof (e as Record<string, unknown>).role === "string"
          ? { role: (e as Record<string, unknown>).role as string, subrole: typeof (e as Record<string, unknown>).subrole === "string" ? (e as Record<string, unknown>).subrole as string : null }
          : null,
      ).filter((e): e is RoleSubroleItem => e !== null);
      return items.length > 0 ? items : [{ role: "", subrole: null }];
    }
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      return [{ role: typeof obj.role === "string" ? obj.role : "", subrole: typeof obj.subrole === "string" ? obj.subrole : null }];
    }
  } catch {
    // fall through
  }
  return [{ role: "", subrole: null }];
}

function serializeRoleSubroleItems(items: RoleSubroleItem[]): string {
  if (items.length === 1) return JSON.stringify({ role: items[0].role, subrole: items[0].subrole });
  return JSON.stringify(items.map((e) => ({ role: e.role, subrole: e.subrole })));
}

function RoleSubroleSubForm({
  row,
  onUpdate,
  catalog,
  ontology,
}: Readonly<{
  row: ValueMapRow;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
  catalog: SubroleCatalog | undefined;
  ontology: RoleOntology | null;
}>) {
  const t = useTranslations("sheetsFeed.valueMapping");
  const slotLabel = useSlotLabel(ontology);
  // The open slot ("any role") first, then the owner game's roles in declared order.
  const roleCodes = [OPEN_SLOT_CODE, ...registrationRoles(ontology).map((role) => role.code)];
  const items = parseRoleSubroleItems(row.value);

  const commit = (next: RoleSubroleItem[]) => {
    onUpdate(row.id, { value: serializeRoleSubroleItems(next) });
  };

  const updateItem = (index: number, field: "role" | "subrole", val: string | null) => {
    commit(
      items.map((item, i) => {
        if (i !== index) return item;
        if (field === "role") {
          const nextRole = val ?? "";
          const allowed = optionsForRole(catalog, nextRole).map((option) => option.slug);
          const keep =
            nextRole !== "" &&
            nextRole !== OPEN_SLOT_CODE &&
            item.subrole != null &&
            allowed.includes(item.subrole);
          return { role: nextRole, subrole: keep ? item.subrole : null };
        }
        return { ...item, subrole: val };
      }),
    );
  };

  const addItem = () => commit([...items, { role: "", subrole: null }]);

  const removeItem = (index: number) => {
    if (items.length <= 1) return;
    commit(items.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-1.5">
      {items.map((item, index) => {
        const roleOptions = optionsForRole(catalog, item.role);
        const subroleDisabled = item.role === "" || item.role === OPEN_SLOT_CODE || roleOptions.length === 0;
        return (
          <div key={index} className="flex items-center gap-1.5">
            <Select value={item.role || undefined} onValueChange={(v) => updateItem(index, "role", v)}>
              <SelectTrigger size="sm" className="flex-1">
                <SelectValue placeholder={t("role")} />
              </SelectTrigger>
              <SelectContent>
                {roleCodes.map((code) => (
                  <SelectItem key={code} value={code}>
                    {slotLabel(code)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={item.subrole ?? NONE}
              onValueChange={(v) => updateItem(index, "subrole", v === NONE ? null : v)}
              disabled={subroleDisabled}
            >
              <SelectTrigger size="sm" className="flex-1">
                <SelectValue placeholder={subroleDisabled ? "—" : t("subrole")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{t("none")}</SelectItem>
                {roleOptions.map((option) => (
                  <SelectItem key={option.slug} value={option.slug}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost-destructive"
              size="icon-toolbar"
              className="shrink-0"
              onClick={() => removeItem(index)}
              disabled={items.length <= 1}
              aria-label={t("removeRole")}
              title={t("removeRole")}
            >
              <Minus className="size-3.5" />
            </Button>
          </div>
        );
      })}
      <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-muted-foreground" onClick={addItem}>
        <Plus className="size-3" />
        {t("addRole")}
      </Button>
    </div>
  );
}

function ValueInput({
  kind,
  row,
  onUpdate,
  catalog,
  ontology,
}: Readonly<{
  kind: ValueEditorKind;
  row: ValueMapRow;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
  catalog: SubroleCatalog | undefined;
  ontology: RoleOntology | null;
}>) {
  const t = useTranslations("sheetsFeed.valueMapping");
  const slotLabel = useSlotLabel(ontology);
  if (kind === "number") {
    return (
      <Input
        type="number"
        value={row.value}
        onChange={(event) => onUpdate(row.id, { value: event.target.value })}
        placeholder={t("rankValue")}
      />
    );
  }

  if (kind === "text") {
    return (
      <Input
        value={row.value}
        onChange={(event) => onUpdate(row.id, { value: event.target.value })}
        placeholder={t("mappedValue")}
      />
    );
  }

  if (kind === "role_subrole") {
    return <RoleSubroleSubForm row={row} onUpdate={onUpdate} catalog={catalog} ontology={ontology} />;
  }

  if (kind === "subrole") {
    const options = flattenSubroleOptions(catalog);
    return (
      <Select
        value={row.value || undefined}
        onValueChange={(value) => onUpdate(row.id, { value })}
        disabled={options.length === 0}
      >
        <SelectTrigger>
          <SelectValue placeholder={options.length === 0 ? t("noSubroles") : t("subrole")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  const options =
    kind === "boolean"
      ? BOOLEAN_OPTIONS
      : registrationRoles(ontology).map((role) => ({ value: role.code, label: slotLabel(role.code) }));
  return (
    <Select value={row.value || undefined} onValueChange={(value) => onUpdate(row.id, { value })}>
      <SelectTrigger>
        <SelectValue placeholder={kind === "boolean" ? t("booleanPlaceholder") : t("role")} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Key -> value row editor for a single value-mapping category. */
export function ValueMapEditor({
  title,
  description,
  kind,
  rows,
  canSeed,
  subroleCatalog,
  ontology = null,
  onAdd,
  onUpdate,
  onRemove,
  onSeedDefaults,
}: Readonly<ValueMapEditorProps>) {
  const t = useTranslations("sheetsFeed.valueMapping");
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <div className="flex items-center gap-2">
          {canSeed ? (
            <Button variant="outline" size="sm" onClick={onSeedDefaults}>
              <Sprout className="mr-1.5 size-3.5" />
              {t("seedDefaults")}
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={onAdd}>
            <Plus className="mr-1.5 size-3.5" />
            {t("addRow")}
          </Button>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="text-xs italic text-muted-foreground/60">{t("noMappings")}</p>
      ) : (
        <div className="space-y-2">
          <div className={`grid items-center gap-2 ${kind === "role_subrole" ? "grid-cols-[1fr_2fr_auto]" : "grid-cols-[1fr_1fr_auto]"}`}>
            <Label className={eyebrowClass("muted")}>
              {t("sheetText")}
            </Label>
            <Label className={eyebrowClass("muted")}>
              {t("mappedValue")}
            </Label>
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className={`grid gap-2 ${kind === "role_subrole" ? "grid-cols-[1fr_2fr_auto] items-start" : "grid-cols-[1fr_1fr_auto] items-center"}`}>
              <Input
                value={row.key}
                onChange={(event) => onUpdate(row.id, { key: event.target.value })}
                placeholder={t("textFromSheet")}
              />
              <ValueInput kind={kind} row={row} onUpdate={onUpdate} catalog={subroleCatalog} ontology={ontology} />
              <Button
                variant="ghost"
                size="icon"
                className={`size-9 shrink-0 text-destructive hover:text-destructive${kind === "role_subrole" ? " mt-0.5" : ""}`}
                onClick={() => onRemove(row.id)}
                title={t("removeRow")}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
