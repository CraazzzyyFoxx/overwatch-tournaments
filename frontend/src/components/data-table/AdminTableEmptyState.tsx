import { CircleMinus } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * No rows. When a search or a filter is what emptied the table, the state also
 * offers the way back out of it.
 */
export function AdminTableEmptyState({
  message,
  hasSearch,
  hasFilters,
  onClear
}: Readonly<{
  message: string;
  hasSearch: boolean;
  hasFilters: boolean;
  onClear: () => void;
}>) {
  const narrowed = hasSearch && hasFilters ? "search and filters" : hasSearch ? "search" : "filters";
  return (
    <div className="flex flex-col items-center justify-center gap-2">
      <CircleMinus aria-hidden className="size-5 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">{message}</p>
      {hasSearch || hasFilters ? (
        <>
          <p className="text-xs text-muted-foreground">Nothing matches the current {narrowed}.</p>
          <Button type="button" variant="outline" size="sm" onClick={onClear}>
            {hasSearch && hasFilters ? "Clear search and filters" : hasSearch ? "Clear search" : "Clear filters"}
          </Button>
        </>
      ) : null}
    </div>
  );
}
