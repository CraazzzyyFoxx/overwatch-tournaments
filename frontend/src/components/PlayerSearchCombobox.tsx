"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { History, Search, User, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { usePlayerSearch } from "@/hooks/usePlayerSearch";
import { cn } from "@/lib/utils";
import type { MinimizedUser } from "@/types/user.types";

const MENU_ITEM_CLASS =
  "flex min-h-10 w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-hidden hover:bg-[color:var(--aqt-overlay-4)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-4)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

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
          {/* The frame wears the control surface and the focus ring; `lg` is the
              landing hero's taller field. */}
          <InputGroup className={cn(size === "lg" && "h-11")}>
            <InputGroupAddon>
              <Search aria-hidden />
            </InputGroupAddon>
            <InputGroupInput
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
              // The native clear glyph ignores the theme; the button below replaces it.
              className="[&::-webkit-search-cancel-button]:appearance-none"
            />
            {isSearching || searchValue ? (
              <InputGroupAddon align="inline-end">
                {isSearching ? (
                  <Spinner className="shrink-0" />
                ) : (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t("nav.search.clear")}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={clearSearch}
                    className="-mr-1 shrink-0 text-[color:var(--aqt-fg-faint)]"
                  >
                    <X aria-hidden />
                  </Button>
                )}
              </InputGroupAddon>
            ) : null}
          </InputGroup>
        </PopoverAnchor>
        <PopoverContent
          align="end"
          sideOffset={4}
          collisionPadding={12}
          // The field keeps the caret; the list is pointer/arrow driven.
          onOpenAutoFocus={(event) => event.preventDefault()}
          className="w-[340px] min-w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-24px)] p-1.5"
        >
          <div id={listId} role="listbox" aria-label={t("nav.search.resultsLabel")}>
            {showHistory && history.length > 0 ? (
              <Eyebrow as="p" className="px-2.5 pb-1.5 pt-2">
                {t("nav.search.recent")}
              </Eyebrow>
            ) : null}
            {rows.length === 0 ? (
              <p className="py-6 text-center text-sm text-[color:var(--aqt-fg-muted)]">
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
                      "bg-[color:var(--aqt-overlay-4)]"
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
