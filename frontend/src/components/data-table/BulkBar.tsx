"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * The bar that floats over the table while rows are selected (F4 ·3): how
 * many, how many of those are on other pages, the screen's `bulkActions`,
 * and a way out.
 *
 * Same register as `kit/SaveBar`: a bar that exists only while there is
 * something to act on. The table renders it, not the screen, so the toolbar
 * never changes with the selection — bulk actions in the toolbar row used to
 * be mistaken for filters, and shifted the row as the selection came and went.
 */
export function BulkBar({
  count,
  offPage,
  onClear,
  children
}: Readonly<{ count: number; offPage: number; onClear: () => void; children: ReactNode }>) {
  const t = useTranslations("kit.actions");
  const tableT = useTranslations("kitTable.dataTableExtra");

  return (
    <Card
      role="region"
      aria-label={t("bulkActions")}
      className="fixed bottom-4 left-1/2 z-30 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center gap-3 bg-card/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-card/80"
    >
      <p className="text-sm text-muted-foreground">
        {t.rich("selectedSummary", {
          count,
          num: (chunks) => <span className="font-medium tabular-nums text-foreground">{chunks}</span>
        })}
        {offPage > 0 ? (
          <span className="ml-2 text-xs tabular-nums" title={tableT("selectedRowsOtherPages")}>
            {tableT("selectedOnOtherPages", { count: offPage })}
          </span>
        ) : null}
      </p>
      {children}
      <Button type="button" variant="ghost" size="icon-sm" aria-label={t("clearSelection")} onClick={onClear}>
        <X aria-hidden />
      </Button>
    </Card>
  );
}
