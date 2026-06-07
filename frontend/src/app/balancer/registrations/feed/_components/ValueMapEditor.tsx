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

export type ValueEditorKind = "boolean" | "role" | "text" | "number";

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
          <div className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
            <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
              Sheet text
            </Label>
            <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
              Mapped value
            </Label>
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
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
