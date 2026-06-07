"use client";

import { ChevronLeft, ChevronRight, Loader2, RefreshCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MappingCatalog,
  MappingPreviewDisposition,
  MappingPreviewResponseV2,
  MappingTargetState,
} from "@/types/balancer-admin.types";

import { PreviewTable } from "./PreviewTable";

interface PreviewTabProps {
  catalog: MappingCatalog;
  mappingState: Record<string, MappingTargetState>;
  preview: MappingPreviewResponseV2 | null;
  activeRowIndex: number;
  isRefreshing: boolean;
  canPreview: boolean;
  onRefresh: () => void;
  onChangeRow: (index: number) => void;
}

const DISPOSITION_VARIANT: Record<MappingPreviewDisposition, "default" | "secondary" | "outline"> = {
  create: "default",
  update: "secondary",
  skip: "outline",
};

export function PreviewTab({
  catalog,
  mappingState,
  preview,
  activeRowIndex,
  isRefreshing,
  canPreview,
  onRefresh,
  onChangeRow,
}: PreviewTabProps) {
  const rowCount = preview?.rows.length ?? 0;
  const safeIndex = Math.min(Math.max(activeRowIndex, 0), Math.max(rowCount - 1, 0));
  const activeRow = preview?.rows[safeIndex] ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium">Preview</p>
          {preview ? (
            <div className="flex items-center gap-1.5">
              <Badge variant="default">{preview.create_count} create</Badge>
              <Badge variant="secondary">{preview.update_count} update</Badge>
              <Badge variant="outline">{preview.skip_count} skip</Badge>
            </div>
          ) : null}
        </div>
        <Button variant="outline" onClick={onRefresh} disabled={isRefreshing || !canPreview}>
          {isRefreshing ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCcw className="mr-2 h-4 w-4" />
          )}
          Refresh preview
        </Button>
      </div>

      {!canPreview ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/60 py-12 text-center">
          <p className="text-sm text-muted-foreground">Set a sheet URL to preview parsed rows.</p>
        </div>
      ) : !preview ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/60 py-12 text-center">
          <p className="text-sm text-muted-foreground">No preview yet.</p>
          <p className="mt-1 text-xs text-muted-foreground/60">
            Click “Refresh preview” to fetch sample rows with the current mapping.
          </p>
        </div>
      ) : rowCount === 0 || !activeRow ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/60 py-12 text-center">
          <p className="text-sm text-muted-foreground">The sheet returned no sample rows.</p>
        </div>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  Row {activeRow.row_index}
                  <Badge variant={DISPOSITION_VARIANT[activeRow.disposition]} className="capitalize">
                    {activeRow.disposition}
                  </Badge>
                </CardTitle>
                <CardDescription>
                  Sample row {safeIndex + 1} of {rowCount}
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8"
                  disabled={safeIndex <= 0}
                  onClick={() => onChangeRow(safeIndex - 1)}
                  title="Previous row"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {safeIndex + 1} / {rowCount}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-8"
                  disabled={safeIndex >= rowCount - 1}
                  onClick={() => onChangeRow(safeIndex + 1)}
                  title="Next row"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {activeRow.warnings.length > 0 ? (
              <Alert>
                <AlertTitle>
                  {activeRow.warnings.length} warning{activeRow.warnings.length === 1 ? "" : "s"}
                </AlertTitle>
                <AlertDescription>
                  <ul className="mt-1 space-y-1">
                    {activeRow.warnings.map((warning, index) => (
                      <li key={`${warning.target ?? "row"}-${index}`} className="text-xs">
                        {warning.target ? <span className="font-mono">{warning.target}</span> : null}
                        {warning.target ? " — " : ""}
                        {warning.message}
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            ) : null}
            <PreviewTable targets={catalog.targets} mappingState={mappingState} row={activeRow} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
