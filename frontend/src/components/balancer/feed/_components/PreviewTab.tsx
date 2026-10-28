"use client";

import { ChevronLeft, ChevronRight, RefreshCcw } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { Spinner } from "@/components/ui/spinner";

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
  const t = useTranslations("sheetsFeed.preview");
  const rowCount = preview?.rows.length ?? 0;
  const safeIndex = Math.min(Math.max(activeRowIndex, 0), Math.max(rowCount - 1, 0));
  const activeRow = preview?.rows[safeIndex] ?? null;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex flex-wrap items-center gap-2">
            {t("title")}
            {preview ? (
              <span className="flex items-center gap-1.5">
                <Badge variant="default">{t("create", { count: preview.create_count })}</Badge>
                <Badge variant="secondary">{t("update", { count: preview.update_count })}</Badge>
                <Badge variant="outline">{t("skip", { count: preview.skip_count })}</Badge>
              </span>
            ) : null}
          </CardTitle>
          <CardDescription>
            {activeRow ? t("sampleRow", { current: safeIndex + 1, total: rowCount }) : t("sampleRowsDescription")}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {activeRow ? (
            <>
              <Button
                variant="outline"
                size="icon-toolbar"
                disabled={safeIndex <= 0}
                onClick={() => onChangeRow(safeIndex - 1)}
                aria-label={t("previousRow")}
                title={t("previousRow")}
              >
                <ChevronLeft aria-hidden />
              </Button>
              <span className="text-caption tabular-nums text-muted-foreground">
                {safeIndex + 1} / {rowCount}
              </span>
              <Button
                variant="outline"
                size="icon-toolbar"
                disabled={safeIndex >= rowCount - 1}
                onClick={() => onChangeRow(safeIndex + 1)}
                aria-label={t("nextRow")}
                title={t("nextRow")}
              >
                <ChevronRight aria-hidden />
              </Button>
            </>
          ) : null}
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing || !canPreview}>
            {isRefreshing ? (
              <Spinner className="mr-2" />
            ) : (
              <RefreshCcw className="mr-2 size-4" />
            )}
            {t("refresh")}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {!canPreview ? (
          <EmptyNote className="text-center">{t("urlRequired")}</EmptyNote>
        ) : !preview ? (
          <EmptyNote title={t("noPreviewTitle")}>
            {t("noPreviewDescription")}
          </EmptyNote>
        ) : rowCount === 0 || !activeRow ? (
          <EmptyNote className="text-center">{t("noRows")}</EmptyNote>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">{t("row", { index: activeRow.row_index })}</span>
              <Badge variant={DISPOSITION_VARIANT[activeRow.disposition]} className="capitalize">
                {activeRow.disposition}
              </Badge>
            </div>
            {activeRow.warnings.length > 0 ? (
              <Alert tone="warning">
                <AlertTitle>
                  {t("warnings", { count: activeRow.warnings.length })}
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
