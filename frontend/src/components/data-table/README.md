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
  selected row and the toolbar shows how many are off-page.
- **Keyboard.** Roving tabindex over rows, arrows/Home/End, Enter opens the row.
- **Columns.** Hide/show with persisted visibility (`columnsStorageKey`), drag to
  reorder, drag the right edge to resize (double-click resets), left-edge sticky prefix
  (`meta.sticky`), header filters (`meta.filter`), search opt-in (`meta.searchValue`).
- **Sorting.** Click to sort; Shift+click stacks a second sort in client mode.
- **Rendering.** Sticky header in its own scroll box, virtualised body past 100 rows,
  grouped rows (`groupRows`), expandable details (`renderExpanded`), density toggle,
  cards below `md` (`renderMobileCard`), search-match highlighting.
- **Row actions.** `createKebabColumn` gives an always-present `⋯` menu that fades in on
  hover/focus; the same actions appear in the right-click / long-press menu, together
  with "Copy “cell”" and "Copy row" (tab-separated).
- **Toolbar.** Search, screen-owned filter bar slot (`toolbar`), CSV export (selection
  or current view), saved views (URL + column visibility, per screen), `actions` slot.

## Public API

```ts
import {
  AdminDataTable, type AdminDataTableProps, type AdminDataTableGroup,
  adminColumnMeta, type AdminColumnMeta,          // column meta: filter, category, sticky, align, searchValue…
  readAdminColumnFilter, type AdminTableFilters,  // filter contract shared with a filter bar
  createKebabColumn, type KebabAction,            // row actions column
  HighlightMatch, useAdminTableSearch,            // for custom cells that want search highlighting
  type PaginatedResponse, type SortDir,
  downloadCsv,
} from "@/components/data-table";
```

Props are documented on `AdminDataTableProps` in `types.ts`.

## Inside

`AdminDataTable.tsx` is the orchestrator: it wires the hooks together, owns the
row-level handlers and renders the card. Everything with a seam of its own sits
next to it.

| File | Responsibility |
| --- | --- |
| `types.ts` | `AdminDataTableProps` (the documented contract), `AdminDataTableGroup`, `PaginatedResponse`, `SortDir`. |
| `useAdminTableState.ts` | Page, search, page size, sort and filters: the state the URL owns, plus the back/forward and page-1-reset rules. |
| `url-state.ts` | Pure `?page=`/`?search=`/`?sort=`/`?dir=` parsing and writing. |
| `filters.ts` | The `meta.filter` contract shared with a filter bar, and its query params. |
| `useAdminTableData.ts` | The two data modes: the server-mode query, or the client-mode rows narrowed by the search box. |
| `useAdminTable.ts` | The TanStack table instance — row models, controlled state, manual vs local paging/sorting/filtering. |
| `useTablePreferences.ts` | Density, column widths and column order in localStorage; rebuilds the order around columns added since it was saved. |
| `useColumnVisibility.ts` | Persisted column visibility behind the "Columns" picker. |
| `useTableScrollBox.ts` | The scroll box the header sticks in, capped to the height left in the viewport. |
| `useVirtualBody.ts` | Rows, group headers and expanded details as one flat list, virtualised past 100 items. |
| `useRowSelectionGestures.ts` | Paint-select, Shift/Ctrl ranges, keyboard selection. |
| `column-layout.tsx` | Column widths, the sticky prefix and the filler column, shared by header and body. |
| `head-cell.tsx` / `body-cells.tsx` / `body-rows.tsx` | One `<th>`, one `<td>` (plus the leading checkbox/chevron cell), and one `<tr>`. |
| `AdminTableHeader.tsx` | The sticky header row, select-all, and the dnd-kit boundary the reorder chunk fills in. |
| `AdminTableHead.tsx` / `ColumnDnd.tsx` | The resizable header cell, and its draggable variant in a lazily imported chunk. |
| `AdminTableToolbar.tsx` | Search, the screen's `toolbar` slot, bulk actions, CSV, density, saved views, column picker, `actions`. |
| `AdminTablePagination.tsx` | The footer: range, rows-per-page, page numbers. |
| `AdminTableMobileList.tsx` | Rows as cards below `md`. |
| `AdminTableEmptyState.tsx` | No rows, and the way out of the search/filter that emptied them. |
| `AdminRowContextMenu.tsx` / `kebab-column.tsx` | Row actions as a right-click menu and as the `⋯` column. |
| `SavedViews.tsx`, `HighlightMatch.tsx`, `csv.ts`, `columns.ts`, `host.ts` | Saved views, search highlighting, CSV export, column meta, host bindings. |

## Porting

Everything taken from the host lives in **`host.ts`** — router (`usePathname`, `Link`),
`cn`, `useIsMobile`, `useLocalStorageState`, and one label class. Point those exports at
the new project's equivalents; nothing else in the folder reaches outside it except:

- shadcn primitives under `@/components/ui/`: `table`, `button`, `input`, `label`,
  `select`, `checkbox`, `dialog`, `dropdown-menu`, `context-menu`, `spinner`, plus two
  small custom ones this repo keeps there — `categorized-column-picker` and
  `infinite-scroll`;
- npm: `@tanstack/react-table` 8, `@tanstack/react-query` 5, `@tanstack/react-virtual` 3,
  `use-debounce`, `lucide-react`, plus `@dnd-kit/{core,sortable,utilities}` — those three
  are imported only by `ColumnDnd.tsx`, which `AdminDataTable` fetches with a dynamic
  `import()` when a pointer first reaches the table, so they are not in the chunk a list
  page loads. Drop that file and the header stays plain (`AdminTableHead`) but keeps
  sorting, resizing and everything else;
- `data-table.css` next to the component: `.admin-sticky-col*`, `.admin-table-head` and
  `.admin-row` — the row's hover / selected / current tint, which the pinned cells
  repaint over their own opaque base. The classes are written by `column-layout.tsx`,
  `head-cell.tsx`, `body-cells.tsx`, `body-rows.tsx` and `AdminTableHeader.tsx`, so the
  stylesheet is imported once by `AdminDataTable.tsx`, the entry that renders them all.

Tests are colocated (`*.behavior.test.tsx`, happy-dom) and mock only `next/navigation`.
