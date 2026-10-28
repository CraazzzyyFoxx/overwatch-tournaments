import { flexRender, type Cell, type Row } from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TableCell } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID, ALIGN_CLASS, ALIGN_FLEX_CLASS, RESPONSIVE_CLASS, readColumnMeta } from "@/components/data-table/columns";
import { HighlightMatch } from "@/components/data-table/HighlightMatch";
import { STICKY_CELL_CLASS, type ColumnLayout } from "@/components/data-table/column-layout";
import type { RowHandlers } from "@/components/data-table/body-rows";

export interface BodyCellContext<TData> {
  layout: ColumnLayout<TData>;
  /** Vertical padding for the current density. */
  cellPadding: string;
  cellAlign: "top" | "middle";
  hasLeadingColumn: boolean;
  /** Columns with a caller-supplied `cell`, which render themselves instead of being highlighted. */
  customCellIds: Set<string>;
  search: string;
}

export interface LeadingCellContext<TData> {
  i18n: (key: string, values?: Record<string, unknown>) => string;
  layout: ColumnLayout<TData>;
  cellPadding: string;
  cellAlign: "top" | "middle";
  enableRowSelection: boolean;
  hasExpandedDetail: boolean;
  selected: boolean;
  expanded: boolean;
  handlers: RowHandlers<TData>;
}

/** The narrow first column: expand chevron and/or selection checkbox. */
export function renderLeadingCell<TData>(
  row: Row<TData>,
  { i18n, layout, cellPadding, cellAlign, enableRowSelection, hasExpandedDetail, selected, expanded, handlers }: LeadingCellContext<TData>
) {
  return (
    <TableCell
      className={cn(
        // `pr-2` is not decoration: `cn` drops shadcn's own `p-2` the moment a
        // one-axis padding lands next to it, and without a right pad the cell
        // measured 32px against the 40 `ADMIN_LEADING_COLUMN_WIDTH` pins the
        // next sticky column at — an 8px hole in the pinned block, with the
        // first scrolling column tucked under it by the same 8px.
        "w-10 min-w-10 pl-4 pr-2",
        cellPadding,
        cellAlign === "top" ? "align-top" : "align-middle",
        layout.stickyLeft.size > 0 && STICKY_CELL_CLASS
      )}
      style={layout.stickyLeft.size > 0 ? { left: 0 } : undefined}
      data-sticky={layout.stickyLeft.size > 0 ? "left" : undefined}
    >
      <div className="flex items-center gap-1.5">
        {hasExpandedDetail ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={row.getToggleExpandedHandler()}
            aria-expanded={expanded}
            aria-label={expanded ? i18n("collapseDetails") : i18n("expandDetails")}
            className="-m-1 shrink-0 text-muted-foreground hover:text-foreground"
          >
            {expanded ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          </Button>
        ) : null}
        {enableRowSelection && row.getCanSelect() ? (
          <Checkbox
            checked={selected}
            onCheckedChange={(checked) => row.toggleSelected(checked === true)}
            onPointerDown={(event) => handlers.checkboxPointerDown(event, row)}
            onClick={handlers.checkboxClick}
            className="touch-none"
            aria-label={i18n("selectRow", { id: row.id })}
          />
        ) : null}
      </div>
    </TableCell>
  );
}

/** One `<td>`: alignment, the sticky/edge padding, and search highlighting for plain cells. */
export function renderBodyCell<TData>(
  cell: Cell<TData, unknown>,
  index: number,
  count: number,
  { layout, cellPadding, cellAlign, hasLeadingColumn, customCellIds, search }: BodyCellContext<TData>
) {
  const isActionColumn = cell.column.id === ADMIN_ACTION_COLUMN_ID;
  const isFirstColumn = index === 0 && !hasLeadingColumn;
  const isLastColumn = index === count - 1;
  const columnMeta = readColumnMeta<TData>(cell.column.columnDef.meta);
  const cellProps = columnMeta.onCell?.(cell.row.original);
  const align = cellProps?.align ?? columnMeta.align ?? (isActionColumn ? "right" : "left");
  const sticky = layout.stickyCell(cell.column.id, layout.getColumnStyle(cell.column));
  const value = columnMeta.ellipsis ? cell.getValue() : undefined;
  // Only a primitive reads the same as a tooltip; anything else would say "[object Object]".
  const title = typeof value === "string" || typeof value === "number" ? String(value) : undefined;
  const content =
    search && !isActionColumn && !customCellIds.has(cell.column.id) ? (
      <HighlightMatch text={String(cell.getValue() ?? "")} query={search} />
    ) : (
      flexRender(cell.column.columnDef.cell, cell.getContext())
    );

  return (
    <TableCell
      key={cell.id}
      className={cn(
        "text-sm",
        cellPadding,
        (columnMeta.valign ?? cellAlign) === "top" ? "align-top" : "align-middle",
        isFirstColumn && "pl-4 text-muted-foreground",
        isLastColumn && "pr-4",
        layout.edgePadding(cell.column.id),
        (isActionColumn || columnMeta.nowrap) && "whitespace-nowrap",
        columnMeta.numeric && "tabular-nums",
        ALIGN_CLASS[align],
        RESPONSIVE_CLASS[columnMeta.responsive ?? "always"],
        columnMeta.className,
        sticky.className,
        cellProps?.className,
      )}
      style={cellProps?.style ? { ...sticky.style, ...cellProps.style } : sticky.style}
      data-sticky={sticky["data-sticky"]}
      data-sticky-edge={sticky["data-sticky-edge"]}
      title={cellProps?.title}
    >
      {isActionColumn ? (
        // The kebab gates its own visibility (hover, focus-within, touch);
        // this wrapper only aligns it.
        <div className="flex w-full items-center justify-end">{content}</div>
      ) : align === "left" ? (
        // Clipped to the cell box: a dragged-narrow column sets width/max-width
        // on the <td>, but content wider than that (a long unbreakable handle)
        // paints straight over the next column unless something hides it.
        // `truncate` also buys the ellipsis; stacked cells keep stacking (their
        // rows are block/flex children, which `nowrap` does not join up).
        <div className={cn("min-w-0", columnMeta.ellipsis === false ? "whitespace-normal break-words" : "truncate")} title={title}>
          {content}
        </div>
      ) : (
        // `text-center` on the <td> does not centre a Tooltip/icon
        // (inline-flex trigger inside a full-width cell). Match the header flex.
        <div
          className={cn(
            "flex w-full items-center overflow-hidden",
            ALIGN_FLEX_CLASS[align],
            columnMeta.ellipsis === false && "whitespace-normal break-words",
          )}
          title={title}
        >
          {/* A flex box does not ellipsise its text; a block child does. */}
          {columnMeta.ellipsis ? <span className="min-w-0 truncate">{content}</span> : content}
        </div>
      )}
    </TableCell>
  );
}
