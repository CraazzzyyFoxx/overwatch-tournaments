"use client";

/**
 * Shared table-column factory for the game-catalogue admin pages (maps,
 * heroes, gamemodes). All three render the same "Aliases" count column, so it
 * lives here instead of being copy-pasted three times.
 *
 * Row actions are NOT here: they are `kit/kebab-column.tsx`'s `createKebabColumn`,
 * the panel's single actions convention.
 */

import { ColumnDef } from "@tanstack/react-table";

import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";

/**
 * "Aliases" column: the alias count as plain text, nothing when there are
 * none. `getAliases` reads the row's alias array so the column works for any
 * catalogue entity shape.
 */
export function createAliasesColumn<T>(
  getAliases: (row: T) => string[] | undefined,
  label: string
): ColumnDef<T> {
  return {
    id: "aliases",
    header: label,
    size: 96,
    enableSorting: false,
    meta: columnMeta<T>({ align: "center" }),
    cell: ({ row }) => {
      const count = getAliases(row.original)?.length ?? 0;
      return count > 0 ? <span className="tabular-nums">{count}</span> : null;
    },
  };
}
