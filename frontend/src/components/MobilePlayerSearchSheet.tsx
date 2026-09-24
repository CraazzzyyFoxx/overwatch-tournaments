"use client";

import { useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Command } from "@/components/ui/command";
import { usePlayerSearch } from "@/hooks/usePlayerSearch";
import PlayerSearchCommandList from "@/components/PlayerSearchCommandList";
import { Spinner } from "@/components/ui/spinner";

/**
 * Full-screen player search for narrow viewports, where the desktop popover
 * (`UserSearch`) is hidden. The sheet itself is the "popover" — no nested
 * Popover/PopoverAnchor, just a scrollable results list below the input.
 * Shares its query/debounce/fetch/keyboard-nav/history behavior with
 * `UserSearch` via `usePlayerSearch()`; closes itself on selection through
 * that hook's `onNavigate` callback.
 */
const MobilePlayerSearchSheet = () => {
  const t = useTranslations();
  const inputId = useId();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [sheetOpen, setSheetOpen] = useState<boolean>(false);

  const {
    searchValue,
    isOpen,
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
  } = usePlayerSearch(() => setSheetOpen(false));

  const handleClear = () => {
    resetSearch();

    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  };

  return (
    <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className="shrink-0 md:hidden"
          aria-label={t("nav.search.mobileTrigger")}
        >
          <Search className="h-5 w-5" aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent
        side="top"
        aria-describedby={undefined}
        className="flex h-[100dvh] max-h-[100dvh] w-full flex-col gap-4 overflow-hidden border-none p-4"
      >
        <SheetTitle className="sr-only">{t("nav.search.mobileTrigger")}</SheetTitle>
        <div className="relative pr-10">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground"
          />
          <Input
            id={inputId}
            ref={inputRef}
            value={searchValue}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            type="text"
            autoComplete="off"
            spellCheck={false}
            inputMode="search"
            enterKeyHint="search"
            autoFocus
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={isOpen}
            aria-controls={listId}
            aria-activedescendant={activeIndex >= 0 ? `${listId}-item-${activeIndex}` : undefined}
            aria-label={t("nav.search.placeholder")}
            placeholder={t("nav.search.placeholder")}
            className="h-10 rounded-xl border-border/60 bg-background/15 pl-9 pr-10 shadow-sm"
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
        <Command className="flex-1 overflow-hidden rounded-xl border border-border/60">
          <PlayerSearchCommandList
            listId={listId}
            listClassName="max-h-full"
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
      </SheetContent>
    </Sheet>
  );
};

export default MobilePlayerSearchSheet;
