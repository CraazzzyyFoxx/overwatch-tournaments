"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Check } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { SearchField } from "@/components/ui/search-field";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useRoleCodeName } from "@/hooks/useRoleName";
import {
  describeAggregate,
  dayKey,
  filterRows,
  firstDir,
  formulaInWords,
  NO_ROLE_PARAM,
  parseTableView,
  QUERY_MAX_LENGTH,
  serializeTableView,
  sortRows,
  type DayCell,
  type LeaderboardTableModel,
  type SortKey,
  type TableColumn,
  type TableView
} from "@/lib/flow/leaderboardTable";
import type { RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";

/** The view as query values (`role`, `q`, `sort`, `dir`); a missing or null key is the default. */
export type TableParams = Partial<Record<"role" | "q" | "sort" | "dir", string | null>>;

// The table is `border-separate` so sticky cells keep their hairline; every cell draws its own.
const CELL = "border-b border-[color:var(--aqt-border)]";
// Opaque, so a column scrolling under the pinned ones is hidden, not shown through.
const PINNED = "sticky z-10 bg-[color:var(--aqt-card)]";
const PLACE_WIDTH = "w-14 min-w-14 max-w-14";

function SortHead({
  sortKey,
  label,
  view,
  onSort,
  align = "right",
  className
}: Readonly<{
  sortKey: SortKey;
  label: string;
  view: TableView;
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
  className?: string;
}>) {
  const t = useTranslations("tournamentDetail.table");
  const active = view.sort === sortKey;
  const Icon = !active ? ArrowUpDown : view.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead
      scope="col"
      aria-sort={active ? (view.dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        CELL,
        "sticky top-0 bg-[color:var(--aqt-card)] px-1.5",
        align === "right" ? "text-right" : "text-left",
        className
      )}
    >
      <Button
        type="button"
        variant="ghost"
        size="label"
        aria-label={t("sortBy", { column: label })}
        onClick={() => onSort(sortKey)}
        className={cn(
          "min-h-8 min-w-8 gap-1 px-1.5 pointer-coarse:min-h-11 pointer-coarse:min-w-11",
          align === "right" ? "justify-end" : "justify-start",
          active ? "text-[color:var(--aqt-teal)] hover:text-[color:var(--aqt-teal)]" : ""
        )}
      >
        <span>{label}</span>
        <Icon aria-hidden className={active ? undefined : "text-[color:var(--aqt-fg-faint)] opacity-60"} />
      </Button>
    </TableHead>
  );
}

/** One day's score and place; hover, focus or a tap opens the full line of that day. */
function DayCellView({
  cell,
  column,
  teamNames,
  roleName
}: Readonly<{
  cell: DayCell;
  column: TableColumn;
  teamNames: LeaderboardTableModel["teamNames"];
  roleName: (code: string) => string;
}>) {
  const t = useTranslations("tournamentDetail.table");
  const [open, setOpen] = useState(false);
  const counted = t(cell.counted ? "day.counted" : "day.notCounted");
  const record =
    cell.wins === null && cell.draws === null && cell.losses === null
      ? null
      : `${cell.wins ?? 0}–${cell.draws ?? 0}–${cell.losses ?? 0}`;
  const lines: [string, string][] = [
    ...(cell.teamId === null ? [] : [[t("day.team"), teamNames.get(cell.teamId) ?? `#${cell.teamId}`] as [string, string]]),
    ...(cell.role === null ? [] : [[t("day.role"), roleName(cell.role)] as [string, string]]),
    ...(record === null ? [] : [[t("day.record"), record] as [string, string]]),
    ...(cell.buchholz === null ? [] : [[t("day.buchholz"), `${cell.buchholz}`] as [string, string]]),
    [t("day.place"), `#${cell.place}`],
    [t("day.score"), `${cell.score}`]
  ];

  return (
    <TableCell
      data-counted={cell.counted}
      className={cn(CELL, "p-0 text-right", cell.counted ? "bg-primary/10" : "text-muted-foreground")}
    >
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            // A tap has no hover or focus to open the tooltip, so the click toggles it (and skips Radix's own close).
            onClick={(event) => {
              event.preventDefault();
              setOpen((was) => !was);
            }}
            className="inline-flex min-h-9 w-full items-center justify-end gap-1.5 px-2 py-1 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring pointer-coarse:min-h-11"
          >
            {cell.counted ? <Check aria-hidden className="size-3.5 shrink-0 text-primary" /> : null}
            <span className={cn("aqt-tnum text-sm", cell.counted && "font-semibold text-foreground")}>{cell.score}</span>
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">#{cell.place}</span>
            <span className="sr-only">{counted}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="space-y-1">
          <p className="font-semibold">
            {column.name} · {counted}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {lines.map(([label, value]) => (
              <div key={label} className="col-span-2 grid grid-cols-subgrid">
                <dt className="text-[color:var(--aqt-fg-muted)]">{label}</dt>
                <dd className="aqt-tnum text-right">{value}</dd>
              </div>
            ))}
          </dl>
        </TooltipContent>
      </Tooltip>
    </TableCell>
  );
}

/**
 * The leaderboard as a table: place, name, one column per aggregate input (counted cells highlighted), total. A by-role
 * table is split into one tab per role. The view (role tab, search, sort) lives in `params` when the caller owns it (the
 * public page keeps it in the URL); without them the table keeps it itself.
 */
export function LeaderboardTable({
  table,
  describe = true,
  ontology,
  params,
  onParamsChange
}: Readonly<{
  table: LeaderboardTableModel;
  describe?: boolean;
  /** The game's role dictionary, for role glyphs and names; without it a role shows as its name. */
  ontology?: RoleOntology | null;
  params?: TableParams;
  onParamsChange?: (params: Record<"role" | "q" | "sort" | "dir", string | null>) => void;
}>) {
  const t = useTranslations("tournamentDetail.table");
  const roleName = useRoleCodeName(ontology);
  const words = table.aggregate && describe ? describeAggregate(table.aggregate.config) : null;

  const [local, setLocal] = useState<TableParams>({});
  const view = useMemo(() => parseTableView(params ?? local, table), [params, local, table]);
  // The input owns its text: a URL write lags a keystroke, and a controlled value would drop it.
  const [text, setText] = useState(view.query);
  const query = text.trim();

  const apply = (next: TableView) => {
    const out = serializeTableView(next, table);
    if (onParamsChange) onParamsChange(out);
    else setLocal(out);
  };
  const sortBy = (key: SortKey) =>
    apply({
      ...view,
      query: text,
      sort: key,
      dir: view.sort === key ? (view.dir === "asc" ? "desc" : "asc") : firstDir(key)
    });

  const scoped = useMemo(
    () => (table.byRole ? table.rows.filter((r) => r.role === view.role) : table.rows),
    [table, view.role]
  );
  const shown = useMemo(
    () => sortRows(filterRows(scoped, query), table.columns, view.sort, view.dir),
    [scoped, query, table.columns, view.sort, view.dir]
  );
  const showRoleColumn = !table.byRole && table.rows.some((r) => r.roles.length > 0);
  const columnCount = 2 + (showRoleColumn ? 1 : 0) + table.columns.length + 1;

  const roleLabel = (code: string | null) => (code === null ? t("noRole") : roleName(code));
  const roleGlyph = (code: string, size: number) =>
    ontology ? <PlayerRoleIcon role={code} ontology={ontology} size={size} /> : <span className="text-label">{roleName(code)}</span>;

  return (
    <div className="space-y-3">
      {words ? (
        <div className="space-y-1 px-4.5 pt-3 text-caption text-muted-foreground">
          <p>{t(`formula.mode.${words.mode.key}`, { n: words.mode.n ?? 0 })}</p>
          <p>
            {t(`formula.score.${words.score.key}`, {
              table: words.score.table.map(([place, points]) => `#${place} — ${points}`).join(", "),
              formula: formulaInWords(words.score.formula ?? "", (variable) =>
                t(`formula.variables.${variable}`)
              )
            })}
          </p>
          <p>{t("formula.ties")}</p>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4.5">
        {table.byRole ? (
          <ToggleGroup
            aria-label={t("roleTabs")}
            value={view.role ?? NO_ROLE_PARAM}
            onValueChange={(value) =>
              apply({ ...view, query: text, role: value === NO_ROLE_PARAM ? null : value })
            }
            className="max-w-full overflow-x-auto"
          >
            {table.roles.map((role) => (
              <ToggleGroupItem
                key={role ?? NO_ROLE_PARAM}
                value={role ?? NO_ROLE_PARAM}
                size="default"
                className="h-8 shrink-0 gap-1.5 pointer-coarse:h-11 pointer-coarse:min-w-11"
              >
                {role !== null && ontology ? (
                  <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
                ) : null}
                {roleLabel(role)}
                {query ? (
                  <span className="aqt-tnum font-normal text-[color:var(--aqt-fg-dim)]">
                    {filterRows(
                      table.rows.filter((r) => r.role === role),
                      query
                    ).length}
                  </span>
                ) : null}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        ) : null}
        <SearchField
          label={t("search")}
          placeholder={t("search")}
          size="default"
          maxLength={QUERY_MAX_LENGTH}
          containerClassName="min-w-0 flex-1 basis-56"
          value={text}
          onValueChange={(next) => {
            setText(next);
            apply({ ...view, query: next });
          }}
        />
      </div>
      {table.byRole ? (
        <p className="px-4.5 text-caption text-muted-foreground">{t("byRoleHint")}</p>
      ) : null}
      <p role="status" className="px-4.5 text-caption text-muted-foreground empty:hidden">
        {query ? t("found", { n: shown.length, total: scoped.length }) : null}
      </p>
      <TooltipProvider>
        <Table
          wrapperClassName="max-h-[75vh]"
          className="border-separate border-spacing-0"
        >
          <caption className="sr-only">{t("caption", { name: table.node.name })}</caption>
          <TableHeader>
            <TableRow>
              <SortHead
                sortKey="place"
                label={t("place")}
                view={view}
                onSort={sortBy}
                align="left"
                className={cn("left-0 z-30", PLACE_WIDTH)}
              />
              <SortHead
                sortKey="name"
                label={t("participant")}
                view={view}
                onSort={sortBy}
                align="left"
                className="left-14 z-30 min-w-36"
              />
              {showRoleColumn ? (
                <TableHead scope="col" className={cn(CELL, "sticky top-0 z-20 bg-[color:var(--aqt-card)]")}>
                  {t("role")}
                </TableHead>
              ) : null}
              {table.columns.map((column) => (
                <SortHead
                  key={column.nodeId}
                  sortKey={dayKey(column.nodeId)}
                  label={column.name}
                  view={view}
                  onSort={sortBy}
                  className="z-20 min-w-24"
                />
              ))}
              <SortHead sortKey="total" label={t("total")} view={view} onSort={sortBy} className="z-20 min-w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.key} className="group/row">
                <TableCell className={cn(CELL, PINNED, "left-0 aqt-tnum font-semibold", PLACE_WIDTH)}>
                  {row.place}
                </TableCell>
                <TableCell className={cn(CELL, PINNED, "left-14 min-w-36 max-w-40 truncate font-semibold")} title={row.name}>
                  {row.name}
                </TableCell>
                {showRoleColumn ? (
                  <TableCell className={CELL}>
                    <span className="flex items-center gap-1">
                      {row.roles.map((code) => (
                        <span key={code}>{roleGlyph(code, 18)}</span>
                      ))}
                    </span>
                  </TableCell>
                ) : null}
                {row.cells.map((cell, i) =>
                  cell ? (
                    <DayCellView
                      key={table.columns[i].nodeId}
                      cell={cell}
                      column={table.columns[i]}
                      teamNames={table.teamNames}
                      roleName={roleName}
                    />
                  ) : (
                    <TableCell key={table.columns[i].nodeId} className={cn(CELL, "text-right text-muted-foreground")}>
                      <span aria-hidden>—</span>
                      <span className="sr-only">{t("legend.missing")}</span>
                    </TableCell>
                  )
                )}
                <TableCell className={cn(CELL, "aqt-tnum text-right font-semibold")}>
                  {row.total ?? "—"}
                </TableCell>
              </TableRow>
            ))}
            {shown.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columnCount} className="py-6 text-center text-muted-foreground">
                  {query ? t("noResults", { query }) : t("empty")}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TooltipProvider>
      {table.columns.length > 0 ? (
        <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4.5 pb-3 text-caption text-muted-foreground">
          <li className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-sm bg-primary/10 px-1.5 py-0.5 font-semibold text-foreground">
              <Check aria-hidden className="size-3.5 text-primary" />
              <span className="aqt-tnum">6</span>
            </span>
            {t("legend.counted")}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="aqt-tnum rounded-sm px-1.5 py-0.5">6</span>
            {t("legend.notCounted")}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="rounded-sm px-1.5 py-0.5">—</span>
            {t("legend.missing")}
          </li>
        </ul>
      ) : null}
    </div>
  );
}
