# admin-data-table

A self-contained admin list table on TanStack Table. Copy this folder into another
project, satisfy `host.ts`, and it works.

## What it does

- **Two data modes.** Server (`queryKey`/`queryFn`, one page per request) or client
  (`rows`, everything in memory: search, sort, filters and paging run locally).
- **URL is the state.** Page, search, page size, sort (`?sort=a,b&dir=asc,desc`) and
  column filters are mirrored into the query string and restored from it; back/forward
  works.
- **Selection.** Checkbox column with paint-select (press and sweep), Shift+click range,
  Ctrl/Cmd+click toggle, sweep on the row body, Shift+arrow keyboard range, Space,
  Ctrl+A, Escape. Server-mode selection survives paging; `bulkActions` receives every
  selected row and returns only its buttons: the table shows them in a floating
  selection bar with the count, the off-page count and a clear button.
- **Keyboard.** Roving tabindex over rows, arrows/Home/End, Enter opens the row.
- **Columns.** Hide/show with persisted visibility (`columnsStorageKey`), drag to
  reorder, drag the right edge to resize (double-click resets), header filters
  (`meta.filter`), search opt-in (`meta.searchValue`). Layout keys on `meta`:
  - `sticky: true | "left" | "right"` — pin a left-edge prefix or a right-edge suffix (the actions column joins it); pinned columns declare `size`.
  - `align`, `valign: "top" | "middle"` — horizontal alignment; per-column override of the table's `cellAlign`.
  - `ellipsis` — unset truncates left-aligned cells, `false` wraps, `true` truncates and adds a `title`.
  - `nowrap` — keep the cell on one line.
  - `className` (`<th>` and `<td>`), `headerClassName` (`<th>` only), `headerTooltip` — an info icon beside the label.
  - `onCell(row)` — per-row `<td>` `className` / `style` / `align` / `title`; no `colSpan`/`rowSpan`.
- **Sorting.** Click to sort; Shift+click stacks a second sort in client mode.
- **Rendering.** Sticky header in its own scroll box, virtualised body past 100 rows,
  grouped rows (`groupRows`, with the reader's choice in the View menu via `groupBy`),
  expandable details (`renderExpanded`), density, cards below `md` (`renderMobileCard`),
  search-match highlighting, a `summary` line at the foot. The table is its own card;
  `framed={false}` drops that frame when a card around it already has one.
- **Row actions.** `createKebabColumn` gives an always-present `⋯` menu that fades in on
  hover/focus; the same actions appear in the right-click / long-press menu, together
  with "Copy “cell”" and "Copy row" (tab-separated).
- **Toolbar.** One row in three zones, each with one meaning; the table lays them out,
  the screen only says what goes in which:
  - *narrow the list* — the search box and the screen's `FilterBar` (`toolbar`);
  - *how it is shown* — one "View" menu on every width: CSV export (selection or
    current view), density, grouping (`groupBy`), saved views (URL + column
    visibility, per screen), columns (`columnsStorageKey`);
  - *what the screen does* — `commands`, data rather than JSX (`TableCommand`):
    outline buttons, the one `primary` last; a permission the reader lacks is
    `hidden`, a precondition is a `disabledReason` shown as text.

  Narrow is the toolbar's own width (under 640px, so a table beside an open Inspector
  folds too), and it stays one row: the search, the filter picker as an icon with the
  active count, the View menu — opening with the secondary commands — and the primary
  as its icon. Active chips and a disabled primary's reason take a row below, only
  while there are any.

## Public API

```ts
import {
  DataTable, type DataTableGroup, type DataTableGroupBy,
  type TableCommand,                              // a screen's command over the list, laid out by the toolbar
  columnMeta, readColumnMeta,                     // column meta: filter, category, sticky, align, valign, ellipsis, nowrap, onCell, headerTooltip, searchValue…
  readAdminColumnFilter, type AdminTableFilters,  // filter contract shared with a filter bar
  createKebabColumn, type KebabAction,            // row actions column
} from "@/components/data-table";
```

Props are documented on `DataTableProps` in `types.ts`.

## A list screen

Every admin list screen has the same shape, so the next one is a copy of the
last. `components/admin/encounters/`, `encounter-reports/` and `pregame-rooms/`
are the reference; `app/admin/matches/page.tsx` is the page in front of them.

| File | Holds |
| --- | --- |
| `app/admin/<route>/page.tsx` | The page header, the permission gate, and `<XBrowser />`. Nothing else — no columns, no queries, no dialogs. |
| `components/admin/<x>/XBrowser.tsx` | The screen: `useQueryParams({ resetOnChange: [], shallow: true })` for `?id=`, `useFilters(defs)`, the `DataTable`, the `Inspector`, the dialogs and mutations. `pageRows` (and `total` or any other response field) comes from `onPageRowsChange(rows, page)`, never from inside `queryFn`. |
| `components/admin/<x>/useXColumns.tsx` | `useMemo`'d `ColumnDef[]`, taking permissions and the callbacks the kebab needs. Icon-only and badge-only columns declare `meta.align: "center"`. |
| `components/admin/<x>/filters.ts` | The `FilterDef[]` builder for the chip row. |
| `components/admin/<x>/model.ts` | Pure row shaping, labels, sort helpers — the part that gets a unit test. |
| `components/admin/<x>/XInspectorPanel.tsx` | The inspector body (and its header actions), fetching only what the open row needs. |
| `components/admin/<x>/XCells.tsx` | Cell components shared by the columns and the inspector, when there are any. |

A file that only a sibling needs stays out of the table: a form hook
(`useXForm.ts`), a scope hook (`useXScope.ts`), a dialog. No file over 600
lines; split by section or hook, never by line count.

## Inside

`DataTable.tsx` is the orchestrator: it wires the hooks together, owns the
row-level handlers (handed to the rows as one stable dispatcher) and the
roving-focus row, and renders the card. Everything with a seam of its own sits
next to it.

| File | Responsibility |
| --- | --- |
| `types.ts` | `DataTableProps` (the documented contract), `TableCommand`, `DataTableGroup`, `DataTableGroupBy`, `PaginatedResponse`, `SortDir`. |
| `useAdminTableState.ts` | Page, search, page size, sort and filters: the state the URL owns, plus the back/forward and page-1-reset rules. |
| `url-state.ts` | Pure `?page=`/`?search=`/`?sort=`/`?dir=` parsing and writing. |
| `filters.ts` | The `meta.filter` contract shared with a filter bar, and its query params. |
| `useAdminTableData.ts` | The two data modes: the server-mode query (one page object per result), or the client-mode rows narrowed by the search box. |
| `useAdminTable.ts` | The TanStack table instance — row models, controlled state, manual vs local paging/sorting/filtering; memoised column filters keep row objects stable. |
| `useTablePreferences.ts` | Density, column widths and column order in localStorage; rebuilds the order around columns added since it was saved, memoised so TanStack's column list keeps its identity. |
| `useColumnVisibility.ts` | Persisted column visibility behind the View menu's "Columns". |
| `useTableScrollBox.ts` | The scroll box the header sticks in, capped to the height left in the viewport. |
| `useVirtualBody.ts` | Rows, group headers and expanded details as one flat list, virtualised past 100 items. |
| `useRowSelectionGestures.ts` | Paint-select, Shift/Ctrl ranges, keyboard selection. |
| `column-layout.tsx` | Column widths, the sticky prefix and suffix, and the filler column, shared by header and body; memoised in `DataTable` on the visible columns, sizing and density. |
| `head-cell.tsx` / `body-cells.tsx` / `body-rows.tsx` | One `<th>`, one `<td>` (plus the leading checkbox/chevron cell), and one `<tr>`: a memoised `BodyRow` that repaints only when its own props (selected, expanded, current, tabbable, layout, debounced search) change. |
| `AdminTableHeader.tsx` | The sticky header row, select-all, and the dnd-kit boundary the reorder chunk fills in. |
| `AdminTableHead.tsx` / `ColumnDnd.tsx` | The resizable header cell, and its draggable variant in a lazily imported chunk. |
| `AdminTableToolbar.tsx` / `toolbar-context.ts` | The toolbar's three zones (search + the screen's `toolbar`; the View menu: CSV, density, grouping, saved views, columns; `commands`) and `useNarrowToolbar`, the toolbar's own width; the context tells the screen's `FilterBar` when it is narrow. |
| `BulkBar.tsx` | The floating selection bar around the screen's `bulkActions`. |
| `AdminTableMobileList.tsx` | Rows as cards below `md`. |
| `AdminTableEmptyState.tsx` | No rows, and the way out of the search/filter that emptied them. |
| `AdminRowContextMenu.tsx` / `kebab-column.tsx` | Row actions as one right-click / long-press menu per table (the `<tbody>` is its trigger; it resolves the row when it opens) and as the `⋯` column. |
| `SavedViews.tsx`, `HighlightMatch.tsx`, `csv.ts`, `columns.ts`, `host.ts` | Saved views, search highlighting, CSV export, column meta, host bindings. |

## Porting

Everything taken from the host lives in **`host.ts`** — router (`usePathname`, `Link`),
`cn`, `useIsMobile`, `useLocalStorageState`, and one label class. Point those exports at
the new project's equivalents; nothing else in the folder reaches outside it except:

- shadcn primitives under `@/components/ui/`: `table`, `button`, `input`, `label`,
  `select`, `checkbox`, `dialog`, `dropdown-menu` (with its radio items), `context-menu`,
  `card`, `spinner`, `tooltip`, `search-field`, plus one small custom one this repo keeps
  there — `infinite-scroll`;
- npm: `@tanstack/react-table` 8, `@tanstack/react-query` 5, `@tanstack/react-virtual` 3,
  `use-debounce`, `lucide-react`, plus `@dnd-kit/{core,sortable,utilities}` — those three
  are imported only by `ColumnDnd.tsx`, which `DataTable` fetches with a dynamic
  `import()` when a pointer first reaches the table, so they are not in the chunk a list
  page loads. Drop that file and the header stays plain (`AdminTableHead`) but keeps
  sorting, resizing and everything else;
- the pinned-column surface and the row-state tint are Tailwind classes:
  `STICKY_CELL_CLASS` / `STICKY_HEAD_CLASS` / `HEAD_SURFACE_CLASS` in `column-layout.tsx`
  (pinned cells mark themselves with `data-sticky="left|right"` and `data-sticky-edge`),
  the row's `--admin-row-tint` in `body-rows.tsx`, and the pinned surface
  `--admin-sticky-bg` on `DataTable`'s root. The tint is registered with `@property`
  in `globals.css` so a state change fades; a port needs that one rule.

Tests are colocated (`*.behavior.test.tsx`, happy-dom) and mock only `next/navigation`.
