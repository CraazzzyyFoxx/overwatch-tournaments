"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Loader2, Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useDebounce } from "use-debounce";
import userService from "@/services/user.service";
import { MinimizedUser } from "@/types/user.types";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { getPlayerSlug } from "@/utils/player";

const UserSearch = () => {
  const t = useTranslations();
  const inputId = useId();
  const listId = useId();
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchData, setSearchData] = useState<MinimizedUser[]>([]);
  const [searchValue, setSearchValue] = useState<string>("");
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const [debouncedSearchValue] = useDebounce(searchValue, 300);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [contentWidth, setContentWidth] = useState<number | undefined>(undefined);
  const { push } = useRouter();

  const query = debouncedSearchValue.trim();
  const inputQuery = searchValue.trim();
  const canSearch = query.length >= 2;
  const canShowResults = inputQuery.length >= 2;

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

  // Render-time state synchronization
  if (!canSearch) {
    if (isSearching) setIsSearching(false);
    if (searchData.length > 0) setSearchData([]);
  }

  const [prevQuery, setPrevQuery] = useState(query);
  if (query !== prevQuery) {
    setPrevQuery(query);
    if (canSearch) {
      setIsSearching(true);
    }
  }

  const targetActiveIndex = (!isOpen || searchData.length === 0)
    ? -1
    : (activeIndex < 0 || activeIndex >= searchData.length)
      ? 0
      : activeIndex;

  if (targetActiveIndex !== activeIndex) {
    setActiveIndex(targetActiveIndex);
  }

  useEffect(() => {
    if (!canSearch) return;

    const controller = new AbortController();
    let isActive = true;

    userService
      .searchUsers(query, controller.signal)
      .then((users) => {
        if (!isActive) return;
        setSearchData(users);
      })
      .catch((error: unknown) => {
        const isAbortError =
          typeof error === "object" &&
          error !== null &&
          "name" in error &&
          (error as { name?: string }).name === "AbortError";

        if (isAbortError) return;
        console.error("Error searching users:", error);
        if (isActive) {
          setSearchData([]);
        }
      })
      .finally(() => {
        if (isActive) {
          setIsSearching(false);
        }
      });

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [canSearch, query]);

  useEffect(() => {
    if (activeIndex < 0) return;

    itemRefs.current[activeIndex]?.scrollIntoView({
      block: "nearest"
    });
  }, [activeIndex]);

  const emptyMessage = isSearching
    ? t("nav.search.searching")
    : canShowResults
      ? t("nav.search.empty")
      : t("nav.search.minChars");

  const handleSelect = (user: MinimizedUser) => {
    setIsOpen(false);
    setSearchValue("");
    setSearchData([]);
    setActiveIndex(-1);
    push(`/users/${getPlayerSlug(user.name)}`);
  };

  const handleClear = () => {
    setIsOpen(false);
    setSearchValue("");
    setSearchData([]);
    setActiveIndex(-1);
    setIsSearching(false);

    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  };

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextValue = event.target.value;

    setSearchValue(nextValue);
    setIsOpen(nextValue.trim().length > 0);

    if (nextValue.trim().length === 0) {
      setSearchData([]);
      setActiveIndex(-1);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (isOpen) {
        event.preventDefault();
        setIsOpen(false);
      }

      return;
    }

    if (!canShowResults || isSearching || searchData.length === 0) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIsOpen(true);
      setActiveIndex((currentIndex) =>
        currentIndex < searchData.length - 1 ? currentIndex + 1 : 0
      );
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setIsOpen(true);
      setActiveIndex((currentIndex) =>
        currentIndex > 0 ? currentIndex - 1 : searchData.length - 1
      );
      return;
    }

    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      handleSelect(searchData[activeIndex]);
    }
  };

  return (
    <div ref={containerRef} className="relative liquid-glass">
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverAnchor asChild>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
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
              placeholder={t("nav.search.placeholder")}
              className={cn(
                "h-10 rounded-xl border-border/60 bg-background/15 pl-9 pr-10 shadow-sm transition-all duration-200 hover:bg-background/20 focus-visible:ring-2 focus-visible:ring-ring/30 sm:w-[300px] md:w-[200px] lg:w-[300px]",
                isOpen && "border-ring/40 bg-background/20 shadow-lg"
              )}
            />
            {isSearching ? (
              <Loader2 className="pointer-events-none absolute right-3 top-3 h-4 w-4 animate-spin text-muted-foreground" />
            ) : searchValue.length > 0 ? (
              <button
                type="button"
                aria-label={t("nav.search.clear")}
                className="absolute right-2.5 top-1/2 inline-flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
                onMouseDown={(event) => event.preventDefault()}
                onClick={handleClear}
              >
                <X className="h-3.5 w-3.5" />
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
            <CommandList id={listId} role="listbox" aria-label={t("nav.search.resultsLabel")}>
              <CommandEmpty>{emptyMessage}</CommandEmpty>
              <CommandGroup>
                {searchData.map((item, index) => (
                  <CommandItem
                    key={`${item.id}:${item.name}`}
                    id={`${listId}-item-${index}`}
                    ref={(node) => {
                      itemRefs.current[index] = node;
                    }}
                    value={`${item.name} ${item.id}`}
                    aria-selected={activeIndex === index}
                    className={cn(
                      "rounded-md px-3 py-2",
                      activeIndex === index && "bg-accent text-accent-foreground"
                    )}
                    onMouseEnter={() => setActiveIndex(index)}
                    onMouseDown={(event) => event.preventDefault()}
                    onSelect={() => handleSelect(item)}
                  >
                    <span className="truncate font-medium">{item.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
};

export default UserSearch;
