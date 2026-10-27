"use client";

import { createContext, useContext } from "react";

/**
 * Whether the table's toolbar is folded for a narrow table. The screen's
 * `FilterBar` reads it to put its picker beside the search and its chips on
 * their own row; outside a table it is never narrow.
 */
export const TableToolbarContext = createContext(false);

export function useTableToolbarNarrow(): boolean {
  return useContext(TableToolbarContext);
}
