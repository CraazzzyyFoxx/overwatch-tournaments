import type { ColumnDef } from "@tanstack/react-table";
import { MessageSquareText } from "lucide-react";

import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";

/** A narrow column showing how many organizer notes a row carries; empty for none. Sorts by the count. */
export function notesCountColumn<T>({
  header,
  count,
  label
}: {
  header: string;
  count: (row: T) => number;
  /** The badge's accessible name, e.g. "3 notes". */
  label: (count: number) => string;
}): ColumnDef<T> {
  return {
    id: "notes",
    header,
    accessorFn: count,
    cell: ({ row }) => {
      const value = count(row.original);
      if (value === 0) return null;
      return (
        <span className="inline-flex items-center gap-1 text-caption text-muted-foreground" title={label(value)}>
          <MessageSquareText className="size-3.5" aria-hidden />
          <span className="tabular-nums" aria-label={label(value)}>
            {value}
          </span>
        </span>
      );
    },
    meta: columnMeta<T>({ category: "admin", align: "center" })
  };
}
