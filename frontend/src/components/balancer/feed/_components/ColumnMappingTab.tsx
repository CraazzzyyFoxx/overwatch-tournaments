"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MappingCatalog,
  MappingTargetGroup,
  MappingTargetMode,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { MappingGroupSection } from "./MappingGroupSection";
import { GROUP_DESCRIPTIONS, GROUP_LABELS, GROUP_ORDER, targetsByGroup } from "./mappingConfig";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { StatusDot } from "@/components/ui/status-dot";
import { Spinner } from "@/components/ui/spinner";

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
  onIsListChange: (key: string, is_list: boolean) => void;
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
  onIsListChange,
}: Readonly<ColumnMappingTabProps>) {
  const grouped = targetsByGroup(catalog);
  const hasHeaders = headerKeys.length > 0;

  const visibleGroups = GROUP_ORDER.filter((g) => grouped[g].length > 0);
  const [activeGroup, setActiveGroup] = useState<MappingTargetGroup>(
    visibleGroups[0] ?? "identity",
  );

  const safeActive = visibleGroups.includes(activeGroup) ? activeGroup : (visibleGroups[0] ?? "identity");

  const hasErrors = (group: MappingTargetGroup) =>
    grouped[group].some((t) => errorsByTarget[t.key]);

  // One card: title + Auto-suggest in the header, the group switcher as the
  // first content row, the active group's description as its caption. Three
  // stacked headers (strip, button row, group card) said the same thing thrice.
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle>Column mapping</CardTitle>
          <CardDescription>
            {hasHeaders
              ? `${headerKeys.length} header${headerKeys.length === 1 ? "" : "s"} detected. Map each field to a sheet column, a constant, or disable it.`
              : "Detect headers by running Auto-suggest or a sync."}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={onSuggest} disabled={isSuggesting}>
          {isSuggesting ? (
            <Spinner className="mr-2" />
          ) : (
            <Sparkles className="mr-2 size-4" />
          )}
          Auto-suggest
        </Button>
      </CardHeader>

      <CardContent className="space-y-4">
        {!hasHeaders ? (
          <EmptyNote title="No sheet headers detected yet.">
            Set the sheet URL, then use Auto-suggest (above) or run a sync to read the header row.
            Once headers are available you can map each field visually.
          </EmptyNote>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
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
                      <StatusDot tone="danger" className="ml-1.5" />
                    )}
                  </Button>
                ))}
              </ButtonGroup>
              <p className="text-xs text-muted-foreground">{GROUP_DESCRIPTIONS[safeActive]}</p>
            </div>

            <MappingGroupSection
              key={safeActive}
              group={safeActive}
              targets={grouped[safeActive]}
              mappingState={mappingState}
              headerKeys={headerKeys}
              parsers={catalog.parsers}
              previewByTarget={previewByTarget}
              errorsByTarget={errorsByTarget}
              subroleCatalog={catalog.subrole_catalog}
              onModeChange={onModeChange}
              onColumnsChange={onColumnsChange}
              onValueChange={onValueChange}
              onParserChange={onParserChange}
              onIsListChange={onIsListChange}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
