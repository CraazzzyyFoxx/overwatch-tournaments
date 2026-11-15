"use client";

import { useEffect, useState } from "react";
import { useDebounce } from "use-debounce";

import { DataPagination } from "@craazzzyyfoxx/admin-kit/ui/data-pagination";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SearchField } from "@craazzzyyfoxx/admin-kit/ui/search-field";
import { useQueryParams } from "@/hooks/useQueryParams";

/**
 * The players search, written to `?q=` once typing settles (each value is a server render). Writing `q` resets the
 * page. A `q` changed from outside (the "reset search" action) is read back into the field.
 */
export function PlayersSearch({ label, placeholder }: Readonly<{ label: string; placeholder: string }>) {
  const { searchParams, setParams } = useQueryParams();
  const urlQuery = searchParams?.get("q")?.trim() ?? "";
  const [input, setInput] = useState(urlQuery);
  const [settled] = useDebounce(input.trim(), 300);
  // A URL change from elsewhere is read back into the field; one this field wrote already matches `settled`.
  const [seenUrlQuery, setSeenUrlQuery] = useState(urlQuery);
  if (urlQuery !== seenUrlQuery) {
    setSeenUrlQuery(urlQuery);
    if (urlQuery !== settled) setInput(urlQuery);
  }

  useEffect(() => {
    if (settled !== urlQuery) setParams({ q: settled || null });
    // Only a settled input writes: re-running on `urlQuery` would fight the URL's own change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled]);

  return (
    <SearchField
      label={label}
      placeholder={placeholder}
      value={input}
      onValueChange={setInput}
      containerClassName="w-full sm:w-64"
    />
  );
}

export function PlayersPagination({
  page,
  totalPages,
  summary
}: Readonly<{ page: number; totalPages: number; summary: string }>) {
  const { setParams } = useQueryParams();
  return (
    <DataPagination
      page={page}
      totalPages={totalPages}
      leading={summary}
      onPageChange={(next) => setParams({ page: next > 1 ? next : null })}
      className="mt-3"
    />
  );
}

/** A search that matched nobody, with the way back to the whole table. */
export function PlayersNotFound({
  title,
  description,
  actionLabel
}: Readonly<{ title: string; description: string; actionLabel: string }>) {
  const { setParams } = useQueryParams();
  return (
    <PageStateCard
      state="filtered-empty"
      title={title}
      description={description}
      actionLabel={actionLabel}
      onAction={() => setParams({ q: null })}
    />
  );
}
