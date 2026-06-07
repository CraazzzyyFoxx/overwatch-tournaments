"use client";

import { Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  MappingCatalog,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { MappingGroupSection } from "./MappingGroupSection";
import { GROUP_ORDER, targetsByGroup } from "./mappingConfig";

interface ColumnMappingTabProps {
  catalog: MappingCatalog;
  mappingState: Record<string, MappingTargetState>;
  headerKeys: string[];
  previewByTarget: Record<string, string>;
  errorsByTarget: Record<string, string>;
  isSuggesting: boolean;
  onSuggest: () => void;
  onModeChange: (key: string, mode: MappingTargetMode) => void;
  onColumnsChange: (key: string, columns: string[]) => void;
  onValueChange: (key: string, value: string) => void;
  onParserChange: (key: string, parser: string) => void;
}

export function ColumnMappingTab({
  catalog,
  mappingState,
  headerKeys,
  previewByTarget,
  errorsByTarget,
  isSuggesting,
  onSuggest,
  onModeChange,
  onColumnsChange,
  onValueChange,
  onParserChange,
}: ColumnMappingTabProps) {
  const grouped = targetsByGroup(catalog);
  const hasHeaders = headerKeys.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-4 py-3">
        <div>
          <p className="text-sm font-medium">Column mapping</p>
          <p className="text-xs text-muted-foreground">
            {hasHeaders
              ? `${headerKeys.length} header${headerKeys.length === 1 ? "" : "s"} detected. Map each field to a sheet column, a constant, or disable it.`
              : "Detect headers by running Auto-suggest or a sync from the Source & Sync tab."}
          </p>
        </div>
        <Button variant="outline" onClick={onSuggest} disabled={isSuggesting}>
          {isSuggesting ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="mr-2 h-4 w-4" />
          )}
          Auto-suggest
        </Button>
      </div>

      {!hasHeaders ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/60 py-12 text-center">
          <p className="text-sm text-muted-foreground">No sheet headers detected yet.</p>
          <p className="mt-1 max-w-md text-xs text-muted-foreground/60">
            Set the sheet URL, then use Auto-suggest (above) or run a sync to read the header row.
            Once headers are available you can map each field visually.
          </p>
        </div>
      ) : (
        GROUP_ORDER.map((group) => (
          <MappingGroupSection
            key={group}
            group={group}
            targets={grouped[group]}
            mappingState={mappingState}
            headerKeys={headerKeys}
            parsers={catalog.parsers}
            previewByTarget={previewByTarget}
            errorsByTarget={errorsByTarget}
            onModeChange={onModeChange}
            onColumnsChange={onColumnsChange}
            onValueChange={onValueChange}
            onParserChange={onParserChange}
          />
        ))
      )}
    </div>
  );
}
