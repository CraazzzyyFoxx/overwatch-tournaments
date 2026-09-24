"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { usePlayerSearch } from "@/hooks/usePlayerSearch";
import { Command } from "@/components/ui/command";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import PlayerSearchCommandList from "@/components/PlayerSearchCommandList";
import { Spinner } from "@/components/ui/spinner";

const UserSearch = () => {
  const t = useTranslations();
  const inputId = useId();
  const listId = useId();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [contentWidth, setContentWidth] = useState<number | undefined>(undefined);

  const {
    searchValue,
    isOpen,
    setIsOpen,
    isSearching,
    searchData,
    activeIndex,
    emptyMessage,
    handleSelect,
    handleClear: resetSearch,
    handleChange,
    handleKeyDown,
    setActiveIndex,
    itemRefs,
    history,
    removeFromHistory,
    clearHistory
  } = usePlayerSearch();

  useEffect(() => {
    const container = containerRef.current;

    if (!container) return;

    const syncWidth = () => setContentWidth(container.offsetWidth);

    syncWidth();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(syncWidth);
    observer.observe(container);

    return () => observer.disconnect();
  }, []);

  const handleClear = () => {
    resetSearch();

    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  };

  return (
    <div ref={containerRef} className="relative liquid-glass">
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverAnchor asChild>
          <div className="relative">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground"
            />
            <Input
              id={inputId}
              ref={inputRef}
              value={searchValue}
              onChange={handleChange}
              onFocus={() => setIsOpen(true)}
              onClick={() => setIsOpen(true)}
              onKeyDown={handleKeyDown}
              type="text"
              autoComplete="off"
              spellCheck={false}
              inputMode="search"
              enterKeyHint="search"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={isOpen}
              aria-controls={listId}
              aria-activedescendant={activeIndex >= 0 ? `${listId}-item-${activeIndex}` : undefined}
              aria-label={t("nav.search.placeholder")}
              placeholder={t("nav.search.placeholder")}
              className={cn(
                "h-10 rounded-xl border-border/60 bg-background/15 pl-9 pr-10 shadow-sm transition-all duration-200 hover:bg-background/20 focus-visible:ring-2 focus-visible:ring-ring/30 sm:w-[300px] md:w-[200px] lg:w-[300px]",
                isOpen && "border-ring/40 bg-background/20 shadow-lg"
              )}
            />
            {isSearching ? (
              <Spinner className="pointer-events-none absolute right-3 top-3 text-muted-foreground" />
            ) : searchValue.length > 0 ? (
              <button
                type="button"
                aria-label={t("nav.search.clear")}
                className="absolute right-2.5 top-1/2 inline-flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
                onMouseDown={(event) => event.preventDefault()}
                onClick={handleClear}
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            ) : null}
          </div>
        </PopoverAnchor>
        <PopoverContent
          align="start"
          className="liquid-glass-panel p-0"
          onOpenAutoFocus={(event) => event.preventDefault()}
          style={contentWidth ? { width: `${contentWidth}px` } : undefined}
        >
          <Command className="liquid-glass-surface rounded-xl">
            <PlayerSearchCommandList
              listId={listId}
              searchValue={searchValue}
              emptyMessage={emptyMessage}
              searchData={searchData}
              activeIndex={activeIndex}
              itemRefs={itemRefs}
              history={history}
              handleSelect={handleSelect}
              setActiveIndex={setActiveIndex}
              removeFromHistory={removeFromHistory}
              clearHistory={clearHistory}
            />
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default UserSearch;
