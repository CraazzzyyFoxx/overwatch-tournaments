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
} from "@/components/admin-data-table";
```

Props are documented on `AdminDataTableProps` in `AdminDataTable.tsx`.

## Porting

Everything taken from the host lives in **`host.ts`** — router (`usePathname`, `Link`),
`cn`, `useIsMobile`, `useLocalStorageState`, and one label class. Point those exports at
the new project's equivalents; nothing else in the folder reaches outside it except:

- shadcn primitives under `@/components/ui/`: `table`, `button`, `input`, `label`,
  `select`, `checkbox`, `dialog`, `dropdown-menu`, `context-menu`, plus two small custom
  ones this repo keeps there — `categorized-column-picker` and `infinite-scroll`;
- npm: `@tanstack/react-table` 8, `@tanstack/react-query` 5, `@tanstack/react-virtual` 3,
  `@dnd-kit/{core,sortable,utilities}`, `use-debounce`, `lucide-react`;
- two CSS rules in the global stylesheet: `.admin-sticky-col*` and `.admin-table-head`
  (search `globals.css` for `admin-sticky-col`).

Tests are colocated (`*.behavior.test.tsx`, happy-dom) and mock only `next/navigation`.
