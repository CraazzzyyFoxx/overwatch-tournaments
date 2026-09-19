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
import { EmptyNote } from "@/components/kit/EmptyNote";

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
}: Readonly<PreviewTabProps>) {
  const rowCount = preview?.rows.length ?? 0;
  const safeIndex = Math.min(Math.max(activeRowIndex, 0), Math.max(rowCount - 1, 0));
  const activeRow = preview?.rows[safeIndex] ?? null;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex flex-wrap items-center gap-2">
            Preview
            {preview ? (
              <span className="flex items-center gap-1.5">
                <Badge variant="default">{preview.create_count} create</Badge>
                <Badge variant="secondary">{preview.update_count} update</Badge>
                <Badge variant="outline">{preview.skip_count} skip</Badge>
              </span>
            ) : null}
          </CardTitle>
          <CardDescription>
            {activeRow ? `Sample row ${safeIndex + 1} of ${rowCount}` : "Sample rows parsed with the current mapping."}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {activeRow ? (
            <>
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
            </>
          ) : null}
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing || !canPreview}>
            {isRefreshing ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <RefreshCcw className="mr-2 size-4" />
            )}
            Refresh preview
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {!canPreview ? (
          <EmptyNote className="text-center">Set a sheet URL to preview parsed rows.</EmptyNote>
        ) : !preview ? (
          <EmptyNote title="No preview yet.">
            Click “Refresh preview” to fetch sample rows with the current mapping.
          </EmptyNote>
        ) : rowCount === 0 || !activeRow ? (
          <EmptyNote className="text-center">The sheet returned no sample rows.</EmptyNote>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">Row {activeRow.row_index}</span>
              <Badge variant={DISPOSITION_VARIANT[activeRow.disposition]} className="capitalize">
                {activeRow.disposition}
              </Badge>
            </div>
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
          </>
        )}
      </CardContent>
    </Card>
  );
}
