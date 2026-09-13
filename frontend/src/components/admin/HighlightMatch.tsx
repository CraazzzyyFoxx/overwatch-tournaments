"use client";

import { createContext, useContext } from "react";

/** The admin table's live search query, for custom cells that want to highlight their own text. */
export const AdminTableSearchContext = createContext("");

export function useAdminTableSearch() {
  return useContext(AdminTableSearchContext);
}

/** `text` with every case-insensitive occurrence of `query` wrapped in `<mark>`. */
export function HighlightMatch({ text, query }: Readonly<{ text: string; query: string }>) {
  const needle = query.trim().toLowerCase();
  if (!needle) return text;
  const lower = text.toLowerCase();
  const parts: React.ReactNode[] = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at));
    from = at + needle.length;
    parts.push(
      <mark key={at} className="rounded-sm bg-warning/30 text-inherit">
        {text.slice(at, from)}
      </mark>
    );
  }
  if (parts.length === 0) return text;
  if (from < text.length) parts.push(text.slice(from));
  return parts;
}
