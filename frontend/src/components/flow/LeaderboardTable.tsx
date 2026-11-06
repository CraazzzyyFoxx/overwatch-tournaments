"use client";

import { useTranslations } from "next-intl";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { describeAggregate, type LeaderboardTableModel } from "@/lib/flow/leaderboardTable";
import { cn } from "@/lib/utils";

/** The leaderboard as a table: place, name, one column per aggregate input (counted cells highlighted), total. */
export function LeaderboardTable({
  table,
  describe = true
}: Readonly<{ table: LeaderboardTableModel; describe?: boolean }>) {
  const t = useTranslations();
  const words = table.aggregate && describe ? describeAggregate(table.aggregate.config) : null;

  return (
    <div className="space-y-3">
      {words ? (
        <div className="space-y-1 px-4.5 pt-3 text-caption text-muted-foreground">
          <p>
            {t(`tournamentDetail.table.formula.mode.${words.mode.key}`, { n: words.mode.n ?? 0 })}
          </p>
          <p>
            {t(`tournamentDetail.table.formula.score.${words.score.key}`, {
              table: words.score.table.map(([place, points]) => `#${place} — ${points}`).join(", "),
              formula: words.score.formula ?? ""
            })}
          </p>
          <p>{t("tournamentDetail.table.formula.ties")}</p>
        </div>
      ) : null}
      <Table aria-label={table.node.name}>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">{t("tournamentDetail.table.place")}</TableHead>
            <TableHead>{t("tournamentDetail.table.participant")}</TableHead>
            {table.columns.map((column) => (
              <TableHead key={column.nodeId} className="text-right">
                {column.name}
              </TableHead>
            ))}
            <TableHead className="text-right">{t("tournamentDetail.table.total")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {table.rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell className="aqt-tnum font-semibold">{row.place}</TableCell>
              <TableCell className="font-semibold">{row.name}</TableCell>
              {row.cells.map((cell, i) =>
                cell ? (
                  <TableCell
                    key={table.columns[i].nodeId}
                    data-counted={cell.counted}
                    className={cn(
                      "aqt-tnum text-right",
                      cell.counted ? "bg-primary/10 font-semibold" : "text-muted-foreground"
                    )}
                  >
                    {cell.score}
                    <span className="sr-only">
                      {" "}
                      {t(cell.counted ? "common.flow.counted" : "common.flow.notCounted")}
                    </span>
                  </TableCell>
                ) : (
                  <TableCell
                    key={table.columns[i].nodeId}
                    className="text-right text-muted-foreground"
                  >
                    —
                  </TableCell>
                )
              )}
              <TableCell className="aqt-tnum text-right font-semibold">
                {row.total ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
