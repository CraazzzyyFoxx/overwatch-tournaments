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

export type ValueEditorKind = "boolean" | "role" | "text" | "number" | "role_subrole";

interface ValueMapEditorProps {
  title: string;
  description: string;
  kind: ValueEditorKind;
  rows: ValueMapRow[];
  /** Whether catalog defaults are available to seed. */
  canSeed: boolean;
  onAdd: () => void;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
  onRemove: (id: string) => void;
  onSeedDefaults: () => void;
}

const BOOLEAN_OPTIONS = [
  { value: "true", label: "true" },
  { value: "false", label: "false" },
] as const;

const ROLE_OPTIONS = [
  { value: "tank", label: "Tank" },
  { value: "dps", label: "DPS" },
  { value: "support", label: "Support" },
] as const;

const ROLE_SUBROLE_ROLE_OPTIONS = [
  { value: "flex", label: "Flex (all roles)" },
  { value: "tank", label: "Tank" },
  { value: "dps", label: "DPS" },
  { value: "support", label: "Support" },
] as const;

const ROLE_SUBROLE_SUBROLE_OPTIONS: Record<string, { value: string; label: string }[]> = {
  dps: [
    { value: "hitscan", label: "Hitscan" },
    { value: "projectile", label: "Projectile" },
  ],
  support: [
    { value: "main_heal", label: "Main heal" },
    { value: "light_heal", label: "Light heal" },
  ],
};

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
}: {
  row: ValueMapRow;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
}) {
  const items = parseRoleSubroleItems(row.value);

  const commit = (next: RoleSubroleItem[]) => {
    onUpdate(row.id, { value: serializeRoleSubroleItems(next) });
  };

  const updateItem = (index: number, field: "role" | "subrole", val: string | null) => {
    commit(
      items.map((item, i) => {
        if (i !== index) return item;
        if (field === "role") {
          return { role: val ?? "", subrole: ROLE_SUBROLE_SUBROLE_OPTIONS[val ?? ""] ? item.subrole : null };
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
        const subroleOptions = ROLE_SUBROLE_SUBROLE_OPTIONS[item.role] ?? [];
        return (
          <div key={index} className="flex items-center gap-1.5">
            <Select value={item.role || undefined} onValueChange={(v) => updateItem(index, "role", v)}>
              <SelectTrigger className="h-8 flex-1">
                <SelectValue placeholder="Role" />
              </SelectTrigger>
              <SelectContent>
                {ROLE_SUBROLE_ROLE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={item.subrole ?? undefined}
              onValueChange={(v) => updateItem(index, "subrole", v)}
              disabled={subroleOptions.length === 0}
            >
              <SelectTrigger className="h-8 flex-1">
                <SelectValue placeholder={subroleOptions.length === 0 ? "—" : "Sub-role"} />
              </SelectTrigger>
              <SelectContent>
                {subroleOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-muted-foreground/60 hover:text-destructive"
              onClick={() => removeItem(index)}
              disabled={items.length <= 1}
              title="Remove role"
            >
              <Minus className="size-3.5" />
            </Button>
          </div>
        );
      })}
      <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground" onClick={addItem}>
        <Plus className="size-3" />
        Add role
      </Button>
    </div>
  );
}

function ValueInput({
  kind,
  row,
  onUpdate,
}: {
  kind: ValueEditorKind;
  row: ValueMapRow;
  onUpdate: (id: string, updates: Partial<Pick<ValueMapRow, "key" | "value">>) => void;
}) {
  if (kind === "text" || kind === "number") {
    return (
      <Input
        type={kind === "number" ? "number" : "text"}
        value={row.value}
        onChange={(event) => onUpdate(row.id, { value: event.target.value })}
        placeholder={kind === "number" ? "Rank value" : "Mapped value"}
        className="h-9"
      />
    );
  }

  if (kind === "role_subrole") {
    return <RoleSubroleSubForm row={row} onUpdate={onUpdate} />;
  }

  const options = kind === "boolean" ? BOOLEAN_OPTIONS : ROLE_OPTIONS;
  return (
    <Select value={row.value || undefined} onValueChange={(value) => onUpdate(row.id, { value })}>
      <SelectTrigger className="h-9">
        <SelectValue placeholder={kind === "boolean" ? "true / false" : "Role"} />
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
  onAdd,
  onUpdate,
  onRemove,
  onSeedDefaults,
}: ValueMapEditorProps) {
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <div className="flex items-center gap-2">
          {canSeed ? (
            <Button variant="outline" size="sm" className="h-8" onClick={onSeedDefaults}>
              <Sprout className="mr-1.5 size-3.5" />
              Seed defaults
            </Button>
          ) : null}
          <Button variant="outline" size="sm" className="h-8" onClick={onAdd}>
            <Plus className="mr-1.5 size-3.5" />
            Add row
          </Button>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="text-xs italic text-muted-foreground/60">No mappings yet.</p>
      ) : (
        <div className="space-y-2">
          <div className={`grid items-center gap-2 ${kind === "role_subrole" ? "grid-cols-[1fr_2fr_auto]" : "grid-cols-[1fr_1fr_auto]"}`}>
            <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
              Sheet text
            </Label>
            <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
              Mapped value
            </Label>
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className={`grid gap-2 ${kind === "role_subrole" ? "grid-cols-[1fr_2fr_auto] items-start" : "grid-cols-[1fr_1fr_auto] items-center"}`}>
              <Input
                value={row.key}
                onChange={(event) => onUpdate(row.id, { key: event.target.value })}
                placeholder="Text from sheet"
                className="h-9"
              />
              <ValueInput kind={kind} row={row} onUpdate={onUpdate} />
              <Button
                variant="ghost"
                size="icon"
                className={`size-9 shrink-0 text-destructive hover:text-destructive${kind === "role_subrole" ? " mt-0.5" : ""}`}
                onClick={() => onRemove(row.id)}
                title="Remove row"
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
