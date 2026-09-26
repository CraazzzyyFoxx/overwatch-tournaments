"use client";

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useDebounce } from "use-debounce";
import userService from "@/services/user.service";
import { MinimizedUser } from "@/types/user.types";
import { getPlayerSlug } from "@/lib/player";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";

/** A player search result kept in local recent-search history. */
export type RecentPlayer = Pick<MinimizedUser, "id" | "name">;

const HISTORY_STORAGE_KEY = "player-search-history";
const HISTORY_LIMIT = 8;

/**
 * Shared query/debounce/fetch/keyboard-nav/history behavior behind every
 * player search surface (the desktop popover `UserSearch` and the mobile
 * `MobilePlayerSearchSheet`). Each surface keeps its own JSX-specific state
 * (input/container refs, popover sizing, per-instance element ids) and wires
 * it to this hook's derived state and handlers.
 *
 * `onNavigate` runs alongside — not instead of — the default `push(...)` on
 * select, so a surface that needs to close itself on selection (the mobile
 * sheet) can do so without re-implementing selection.
 */
export function usePlayerSearch(onNavigate?: (user: MinimizedUser) => void) {
  const t = useTranslations();
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchData, setSearchData] = useState<MinimizedUser[]>([]);
  const [searchValue, setSearchValue] = useState<string>("");
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const [debouncedSearchValue] = useDebounce(searchValue, 300);
  const itemRefs = useRef<Array<HTMLDivElement | null>>([]);
  const { push } = useRouter();
  const [history, setHistory] = useLocalStorageState<RecentPlayer[]>(HISTORY_STORAGE_KEY, []);

  const query = debouncedSearchValue.trim();
  const inputQuery = searchValue.trim();
  const canSearch = query.length >= 2;
  const canShowResults = inputQuery.length >= 2;

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
    setHistory((prev) =>
      [{ id: user.id, name: user.name }, ...prev.filter((p) => p.id !== user.id)].slice(0, HISTORY_LIMIT)
    );
    onNavigate?.(user);
    push(`/users/${getPlayerSlug(user.name)}`);
  };

  const handleClear = () => {
    setIsOpen(false);
    setSearchValue("");
    setSearchData([]);
    setActiveIndex(-1);
    setIsSearching(false);
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextValue = event.target.value;

    setSearchValue(nextValue);
    setIsOpen(nextValue.trim().length > 0);

    if (nextValue.trim().length === 0) {
      setSearchData([]);
      setActiveIndex(-1);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
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

  const removeFromHistory = (id: number) => {
    setHistory((prev) => prev.filter((p) => p.id !== id));
  };

  const clearHistory = () => {
    setHistory([]);
  };

  return {
    searchValue,
    isOpen,
    setIsOpen,
    isSearching,
    searchData,
    activeIndex,
    canShowResults,
    emptyMessage,
    handleSelect,
    handleClear,
    handleChange,
    handleKeyDown,
    setActiveIndex,
    itemRefs,
    history,
    removeFromHistory,
    clearHistory
  };
}
