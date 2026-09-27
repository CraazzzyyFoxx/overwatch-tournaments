import { flexRender, type Cell, type Row } from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";

import { TableCell } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID, ALIGN_CLASS, ALIGN_FLEX_CLASS, RESPONSIVE_CLASS, readColumnMeta } from "@/components/data-table/columns";
import { HighlightMatch } from "@/components/data-table/HighlightMatch";
import type { ColumnLayout } from "@/components/data-table/column-layout";
import type { RowSelectionGestures } from "@/components/data-table/useRowSelectionGestures";

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
  layout: ColumnLayout<TData>;
  cellPadding: string;
  cellAlign: "top" | "middle";
  enableRowSelection: boolean;
  hasExpandedDetail: boolean;
  gestures: RowSelectionGestures<TData>;
}

/** The narrow first column: expand chevron and/or selection checkbox. */
export function renderLeadingCell<TData>(
  row: Row<TData>,
  { layout, cellPadding, cellAlign, enableRowSelection, hasExpandedDetail, gestures }: LeadingCellContext<TData>
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
        layout.stickyLeft.size > 0 && "admin-sticky-col"
      )}
      style={layout.stickyLeft.size > 0 ? { left: 0 } : undefined}
    >
      <div className="flex items-center gap-1.5">
        {hasExpandedDetail ? (
          <button
            type="button"
            onClick={row.getToggleExpandedHandler()}
            aria-expanded={row.getIsExpanded()}
            aria-label={row.getIsExpanded() ? "Collapse details" : "Expand details"}
            className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground"
          >
            {row.getIsExpanded() ? (
              <ChevronDown aria-hidden className="size-4" />
            ) : (
              <ChevronRight aria-hidden className="size-4" />
            )}
          </button>
        ) : null}
        {enableRowSelection && row.getCanSelect() ? (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(checked) => row.toggleSelected(checked === true)}
            onPointerDown={gestures.checkboxPointerDown(row)}
            onClick={gestures.checkboxClick}
            className="touch-none"
            aria-label={`Select row ${row.id}`}
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
  const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
  const sticky = layout.stickyCell(cell.column.id, layout.getColumnStyle(cell.column));
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
        cellAlign === "top" ? "align-top" : "align-middle",
        isFirstColumn && "pl-4 text-muted-foreground",
        isLastColumn && "pr-4",
        layout.edgePadding(cell.column.id),
        isActionColumn && "whitespace-nowrap",
        columnMeta.numeric && "tabular-nums",
        ALIGN_CLASS[align],
        RESPONSIVE_CLASS[columnMeta.responsive ?? "always"],
        columnMeta.className,
        sticky.className,
      )}
      style={sticky.style}
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
        <div className="min-w-0 truncate">{content}</div>
      ) : (
        // `text-center` on the <td> does not centre a Tooltip/icon
        // (inline-flex trigger inside a full-width cell). Match the header flex.
        <div className={cn("flex w-full items-center overflow-hidden", ALIGN_FLEX_CLASS[align])}>{content}</div>
      )}
    </TableCell>
  );
}
