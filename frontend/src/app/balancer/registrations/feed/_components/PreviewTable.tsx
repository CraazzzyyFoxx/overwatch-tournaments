"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type {
  MappingPreviewRow,
  MappingTargetDef,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { formatParsedValue, parsedTargetValue } from "./mappingConfig";

interface PreviewTableProps {
  targets: MappingTargetDef[];
  mappingState: Record<string, MappingTargetState>;
  row: MappingPreviewRow;
}

/** Read the source value(s) for a target from the preview row's raw cells. */
function sourceValue(target: MappingTargetDef, state: MappingTargetState | undefined, row: MappingPreviewRow): string {
  if (!state || state.mode === "disabled") {
    return "";
  }
  if (state.mode === "constant") {
    return state.value ?? "";
  }
  return state.columns
    .map((column) => row.sample_raw_row[column] ?? "")
    .filter((cell) => cell.length > 0)
    .join(" | ");
}

export function PreviewTable({ targets, mappingState, row }: PreviewTableProps) {
  const errorByTarget = new Map<string, string>();
  for (const error of row.errors) {
    if (error.target && !errorByTarget.has(error.target)) {
      errorByTarget.set(error.target, error.message);
    }
  }

  // Only show targets that are actually mapped (not disabled), to keep the table focused.
  const visibleTargets = targets.filter((target) => mappingState[target.key]?.mode !== "disabled");

  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[34%]">Field</TableHead>
            <TableHead className="w-[33%]">Source value</TableHead>
            <TableHead className="w-[33%]">Parsed value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleTargets.length === 0 ? (
            <TableRow>
              <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                No fields are mapped yet.
              </TableCell>
            </TableRow>
          ) : (
            visibleTargets.map((target) => {
              const state = mappingState[target.key];
              const error = errorByTarget.get(target.key) ?? null;
              const parsed = formatParsedValue(parsedTargetValue(row.parsed_fields, target.key));
              return (
                <TableRow key={target.key} className={cn(error && "bg-destructive/5")}>
                  <TableCell className="align-top">
                    <span className="text-sm font-medium">{target.label}</span>
                    <p className="font-mono text-[10px] text-muted-foreground/60">{target.key}</p>
                  </TableCell>
                  <TableCell className="align-top text-sm text-muted-foreground">
                    {sourceValue(target, state, row) || <span className="italic text-muted-foreground/50">—</span>}
                  </TableCell>
                  <TableCell className={cn("align-top text-sm", error ? "text-destructive" : "")}>
                    {error ? (
                      <span className="font-medium">{error}</span>
                    ) : parsed ? (
                      parsed
                    ) : (
                      <span className="italic text-muted-foreground/50">—</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
