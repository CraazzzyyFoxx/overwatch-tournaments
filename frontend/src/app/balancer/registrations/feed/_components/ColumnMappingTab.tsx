"use client";

import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import type {
  MappingCatalog,
  MappingTargetGroup,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { MappingGroupSection } from "./MappingGroupSection";
import { GROUP_LABELS, GROUP_ORDER, targetsByGroup } from "./mappingConfig";

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

  const visibleGroups = GROUP_ORDER.filter((g) => grouped[g].length > 0);
  const [activeGroup, setActiveGroup] = useState<MappingTargetGroup>(
    visibleGroups[0] ?? "identity",
  );

  const safeActive = visibleGroups.includes(activeGroup) ? activeGroup : (visibleGroups[0] ?? "identity");

  const hasErrors = (group: MappingTargetGroup) =>
    grouped[group].some((t) => errorsByTarget[t.key]);

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
        <>
          <ButtonGroup>
            {visibleGroups.map((group) => (
              <Button
                key={group}
                variant={safeActive === group ? "default" : "outline"}
                size="sm"
                onClick={() => setActiveGroup(group)}
                className="relative"
              >
                {GROUP_LABELS[group]}
                {hasErrors(group) && (
                  <span className="ml-1.5 inline-flex h-1.5 w-1.5 rounded-full bg-destructive" />
                )}
              </Button>
            ))}
          </ButtonGroup>

          <MappingGroupSection
            key={safeActive}
            group={safeActive}
            targets={grouped[safeActive]}
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
        </>
      )}
    </div>
  );
}
