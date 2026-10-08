"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { History, Search, User, X } from "lucide-react";

import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { usePlayerSearch } from "@/hooks/usePlayerSearch";
import { cn } from "@/lib/utils";
import type { MinimizedUser } from "@/types/user.types";

const MENU_ITEM_CLASS =
  "flex min-h-10 w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-none hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]";

/**
 * The one player search surface: the header's inline combobox (`md`) and the
 * landing hero's wider field are the same control at two sizes. Query,
 * debounce, fetch, keyboard navigation and the recent-search history come from
 * `usePlayerSearch`; selecting a player navigates to their profile.
 */
export function PlayerSearchCombobox({
  size = "md",
  placeholder,
  className,
  autoFocus
}: Readonly<{
  size?: "md" | "lg";
  placeholder: string;
  className?: string;
  autoFocus?: boolean;
}>) {
  const t = useTranslations();
  const listId = useId();

  const {
    searchValue,
    isOpen,
    setIsOpen,
    isSearching,
    searchData,
    activeIndex,
    emptyMessage,
    handleSelect,
    handleChange,
    clearSearch,
    handleKeyDown,
    setActiveIndex,
    itemRefs,
    history
  } = usePlayerSearch();

  const showHistory = searchValue.trim().length === 0;
  const rows: MinimizedUser[] = showHistory ? history : searchData;
  const RowIcon = showHistory ? History : User;

  return (
    <div className={cn("relative", className)}>
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverAnchor asChild>
          <label
            className={cn(
              "flex min-w-0 items-center border border-[color:var(--aqt-border-2)]",
              "text-[color:var(--aqt-fg-faint)] transition-colors duration-150",
              "focus-within:border-[color:var(--aqt-teal)] focus-within:bg-[color:var(--aqt-overlay-3)]",
              size === "lg"
                ? "h-11 gap-2.5 rounded-[var(--aqt-radius-sm)] bg-[color:var(--aqt-overlay-2)] px-3.5"
                : "h-9 gap-2 rounded-[9px] bg-[color:var(--aqt-overlay-1)] px-2.5"
            )}
          >
            <span className="sr-only">{placeholder}</span>
            <Search className="size-4 shrink-0" aria-hidden />
            <input
              type="search"
              role="combobox"
              value={searchValue}
              onChange={handleChange}
              onFocus={() => setIsOpen(true)}
              onClick={() => setIsOpen(true)}
              onKeyDown={handleKeyDown}
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              // Only ever set when the mobile search row was opened by a tap.
              autoFocus={autoFocus}
              aria-expanded={isOpen}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={
                activeIndex >= 0 && !showHistory ? `${listId}-item-${activeIndex}` : undefined
              }
              aria-label={placeholder}
              placeholder={placeholder}
              className={cn(
                "h-full min-w-0 flex-1 border-0 bg-transparent text-[color:var(--aqt-fg)] outline-none",
                "placeholder:text-[color:var(--aqt-fg-faint)]",
                // The native clear glyph ignores the theme; the button below replaces it.
                "[&::-webkit-search-cancel-button]:appearance-none",
                size === "lg" ? "text-ui" : "text-body"
              )}
            />
            {isSearching ? <Spinner className="shrink-0" /> : null}
            {searchValue && !isSearching ? (
              <button
                type="button"
                aria-label={t("nav.search.clear")}
                onMouseDown={(event) => event.preventDefault()}
                onClick={clearSearch}
                className="-mr-1 grid size-6 shrink-0 place-items-center rounded-md text-[color:var(--aqt-fg-faint)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)]"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            ) : null}
          </label>
        </PopoverAnchor>
        <PopoverContent
          align="end"
          sideOffset={8}
          collisionPadding={12}
          // The field keeps the caret; the list is pointer/arrow driven.
          onOpenAutoFocus={(event) => event.preventDefault()}
          className="w-[340px] min-w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-24px)] rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] p-1.5 shadow-[0_18px_50px_rgb(0_0_0/0.5)]"
        >
          <div id={listId} role="listbox" aria-label={t("nav.search.resultsLabel")}>
            {showHistory && history.length > 0 ? (
              <p className="px-2.5 pb-1.5 pt-2 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("nav.search.recent")}
              </p>
            ) : null}
            {rows.length === 0 ? (
              <p className="px-2.5 py-3 text-body text-[color:var(--aqt-fg-muted)]">
                {emptyMessage}
              </p>
            ) : (
              rows.map((player, index) => (
                <div
                  key={`${showHistory ? "recent" : "hit"}:${player.id}`}
                  id={showHistory ? undefined : `${listId}-item-${index}`}
                  ref={(node) => {
                    if (!showHistory) itemRefs.current[index] = node;
                  }}
                  role="option"
                  tabIndex={-1}
                  aria-selected={!showHistory && activeIndex === index}
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => handleSelect(player)}
                  className={cn(
                    MENU_ITEM_CLASS,
                    !showHistory &&
                      activeIndex === index &&
                      "bg-[color:var(--aqt-overlay-3)]"
                  )}
                >
                  <RowIcon className="size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{player.name}</span>
                </div>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
