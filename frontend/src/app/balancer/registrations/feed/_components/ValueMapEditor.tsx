"use client";

import { Plus, Sprout, Trash2 } from "lucide-react";

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

function parseRoleSubroleValue(value: string): { role: string; subrole: string | null } {
  try {
    const parsed = JSON.parse(value) as { role?: unknown; subrole?: unknown };
    return {
      role: typeof parsed.role === "string" ? parsed.role : "",
      subrole: typeof parsed.subrole === "string" ? parsed.subrole : null,
    };
  } catch {
    return { role: "", subrole: null };
  }
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
    const { role, subrole } = parseRoleSubroleValue(row.value);
    const subroleOptions = ROLE_SUBROLE_SUBROLE_OPTIONS[role] ?? [];

    const handleRoleChange = (newRole: string) => {
      const newSubrole = ROLE_SUBROLE_SUBROLE_OPTIONS[newRole] ? subrole : null;
      onUpdate(row.id, { value: JSON.stringify({ role: newRole, subrole: newSubrole }) });
    };

    const handleSubroleChange = (newSubrole: string) => {
      onUpdate(row.id, { value: JSON.stringify({ role, subrole: newSubrole || null }) });
    };

    return (
      <div className="grid grid-cols-2 gap-1.5">
        <Select value={role || undefined} onValueChange={handleRoleChange}>
          <SelectTrigger className="h-9">
            <SelectValue placeholder="Role" />
          </SelectTrigger>
          <SelectContent>
            {ROLE_SUBROLE_ROLE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={subrole ?? undefined}
          onValueChange={handleSubroleChange}
          disabled={subroleOptions.length === 0}
        >
          <SelectTrigger className="h-9">
            <SelectValue placeholder={subroleOptions.length === 0 ? "—" : "Sub-role"} />
          </SelectTrigger>
          <SelectContent>
            {subroleOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
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
            <div key={row.id} className={`grid items-center gap-2 ${kind === "role_subrole" ? "grid-cols-[1fr_2fr_auto]" : "grid-cols-[1fr_1fr_auto]"}`}>
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
                className="size-9 shrink-0 text-destructive hover:text-destructive"
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
