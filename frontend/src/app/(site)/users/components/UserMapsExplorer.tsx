"use client";

import React, { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import Image from "next/image";
import { Search } from "lucide-react";

import userService from "@/services/user.service";
import { UserMapHeroStats, UserMapRead, UserMapsSummary } from "@/types/user.types";
import SearchableImageSelect, {
  type SearchableImageOption
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { PaginationWithLinks } from "@/components/ui/pagination-with-links";
import { getWinrateColor } from "@/utils/colors";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import {
  clampInt,
  formatPercent,
  formatSeconds,
  MIN_COUNT_KEY,
  ORDER_KEY,
  OrderKey,
  PAGE_KEY,
  PER_PAGE_KEY,
  parsePerPage,
  QUERY_KEY,
  SORT_KEY,
  SortKey
} from "@/app/(site)/users/components/user-maps-explorer/utils";

export interface UserMapsExplorerProps {
  userId: number;
}

const HighlightCard = ({
  title,
  subtitle,
  value,
  valueColor
}: {
  title: string;
  subtitle: string;
  value: string;
  valueColor?: string;
}) => {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold tabular-nums" style={valueColor ? { color: valueColor } : undefined}>
          {value}
        </div>
        <div className="mt-1 text-xs text-muted-foreground truncate">{subtitle}</div>
      </CardContent>
    </Card>
  );
};

const HeroStatsChip = ({
  heroStats,
  open,
  onRequestOpen,
  onRequestClose
}: {
  heroStats: UserMapHeroStats;
  open: boolean;
  onRequestOpen: () => void;
  onRequestClose: () => void;
}) => {
  const closeTimeoutRef = useRef<number | null>(null);
  const winrateColor = getWinrateColor(heroStats.win_rate);
  const shareValue = Math.max(0, Math.min(100, heroStats.playtime_share_on_map * 100));

  const clearCloseTimeout = () => {
    if (closeTimeoutRef.current === null) {
      return;
    }
    window.clearTimeout(closeTimeoutRef.current);
    closeTimeoutRef.current = null;
  };

  const scheduleClose = (delayMs = 120) => {
    clearCloseTimeout();
    closeTimeoutRef.current = window.setTimeout(() => {
      onRequestClose();
    }, delayMs);
  };

  useEffect(() => {
    return () => {
      clearCloseTimeout();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          onRequestOpen();
        } else {
          onRequestClose();
        }
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className="h-11 w-11 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`${heroStats.hero.name} on this map`}
          onPointerEnter={(e) => {
            if (e.pointerType !== "mouse") {
              return;
            }
            clearCloseTimeout();
          }}
          onPointerMove={(e) => {
            if (e.pointerType !== "mouse") {
              return;
            }
            clearCloseTimeout();
            if (!open) {
              onRequestOpen();
            }
          }}
          onPointerLeave={(e) => {
            if (e.pointerType !== "mouse") {
              return;
            }
            scheduleClose();
          }}
          onFocus={() => {
            clearCloseTimeout();
            if (!open) {
              onRequestOpen();
            }
          }}
          onBlur={() => {
            scheduleClose(0);
          }}
        >
          <Image
            src={heroStats.hero.image_path}
            alt={heroStats.hero.name}
            width={40}
            height={40}
            className="h-full w-full object-contain select-none"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 data-[state=open]:animate-none data-[state=closed]:animate-none"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onPointerEnter={(e) => {
          if (e.pointerType !== "mouse") {
            return;
          }
          clearCloseTimeout();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType !== "mouse") {
            return;
          }
          scheduleClose();
        }}
      >
        <div className="flex items-start gap-3">
          <div className="h-12 w-12 shrink-0">
            <Image
              src={heroStats.hero.image_path}
              alt={heroStats.hero.name}
              width={48}
              height={48}
              className="h-full w-full object-contain select-none"
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold truncate">{heroStats.hero.name}</div>
            <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
              <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
                <div className="text-muted-foreground">Winrate</div>
                <div className="font-semibold tabular-nums" style={{ color: winrateColor }}>
                  {formatPercent(heroStats.win_rate, 0)}
                </div>
              </div>
              <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
                <div className="text-muted-foreground">Games</div>
                <div className="font-semibold tabular-nums">{heroStats.games}</div>
              </div>
              <div className="rounded-md border border-border/50 bg-muted/10 px-2 py-1">
                <div className="text-muted-foreground">Record</div>
                <div className="font-semibold tabular-nums">
                  {heroStats.win}-{heroStats.loss}-{heroStats.draw}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Playtime on this map</span>
            <span className="tabular-nums">
              {formatSeconds(heroStats.playtime_seconds)} | {shareValue.toFixed(0)}%
            </span>
          </div>
          <div className="mt-2">
            <Progress value={shareValue} aria-label="Playtime share on this map" />
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            Games counted when hero time played is &gt; 60s.
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default function UserMapsExplorer({ userId }: UserMapsExplorerProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const page = clampInt(searchParams.get(PAGE_KEY), 1, 1, 10_000);
  const perPage = parsePerPage(searchParams.get(PER_PAGE_KEY));
  const minCount = clampInt(searchParams.get(MIN_COUNT_KEY), 3, 1, 999);
  const sortRaw = searchParams.get(SORT_KEY);
  const sort: SortKey =
    sortRaw === "count" || sortRaw === "name" || sortRaw === "winrate" ? sortRaw : "winrate";
  const orderRaw = searchParams.get(ORDER_KEY);
  const order: OrderKey = orderRaw === "asc" || orderRaw === "desc" ? orderRaw : "desc";
  const mapsQueryFromUrl = searchParams.get(QUERY_KEY) ?? "";

  const [searchValue, setSearchValue] = useState(mapsQueryFromUrl);
  const [debouncedSearchValue] = useDebounce(searchValue, 300);

  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  const tournamentsQuery = useQuery({
    queryKey: ["user-tournaments", userId],
    queryFn: () => userService.getUserTournaments(userId),
    staleTime: 5 * 60 * 1000
  });

  const tournamentOptions = useMemo<SearchableImageOption[]>(() => {
    return (tournamentsQuery.data ?? []).map((t) => ({
      value: String(t.id),
      label: t.name
    }));
  }, [tournamentsQuery.data]);

  const [activeHeroPopoverKey, setActiveHeroPopoverKey] = useState<string | null>(null);

  useEffect(() => {
    setSearchValue(mapsQueryFromUrl);
  }, [mapsQueryFromUrl]);

  const pushParams = (updates: Record<string, string | null>, resetPage = false) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (!value) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    }
    if (resetPage) {
      next.set(PAGE_KEY, "1");
    }

    startTransition(() => {
      router.push(`${pathname}?${next.toString()}`);
    });
  };

  useEffect(() => {
    const trimmed = debouncedSearchValue.trim();
    if (trimmed === mapsQueryFromUrl) {
      return;
    }
    pushParams({ [QUERY_KEY]: trimmed || null }, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearchValue]);

  useEffect(() => {
    if (perPage === -1 && page !== 1) {
      pushParams({ [PAGE_KEY]: "1" }, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perPage]);

  useEffect(() => {
    if (perPage === -1 && searchParams.get(PER_PAGE_KEY) !== null) {
      pushParams({ [PER_PAGE_KEY]: null }, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perPage, searchParams]);

  const mapsQuery = mapsQueryFromUrl.trim();

  const mapsQueryResult = useQuery({
    queryKey: [
      "user-maps",
      userId,
      page,
      perPage,
      sort,
      order,
      mapsQuery,
      minCount,
      tournamentId
    ],
    queryFn: () =>
      userService.getUserMaps(userId, {
        page,
        perPage,
        sort,
        order,
        query: mapsQuery,
        minCount,
        tournamentId
      }),
    staleTime: 60_000
  });

  const summaryQueryResult = useQuery({
    queryKey: ["user-maps-summary", userId, mapsQuery, minCount, tournamentId],
    queryFn: () => userService.getUserMapsSummary(userId, { query: mapsQuery, minCount, tournamentId }),
    staleTime: 60_000
  });

  const mapsData = mapsQueryResult.data;
  const summary = summaryQueryResult.data as UserMapsSummary | undefined;

  const isLoading = mapsQueryResult.isLoading || summaryQueryResult.isLoading;
  const error = mapsQueryResult.error || summaryQueryResult.error;

  const showingCount = mapsData?.results?.length ?? 0;
  const totalCount = mapsData?.total ?? 0;

  const sortLabel = useMemo(() => {
    if (sort === "count") return "Games";
    if (sort === "name") return "Name";
    return "Winrate";
  }, [sort]);

  const openHeroPopover = (key: string) => {
    setActiveHeroPopoverKey(key);
  };

  const closeHeroPopover = (key: string) => {
    setActiveHeroPopoverKey((current) => (current === key ? null : current));
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <HighlightCard
          title="Overall winrate"
          subtitle={
            summary
              ? `${summary.overall.win}-${summary.overall.loss}-${summary.overall.draw} | ${summary.overall.total_games} games`
              : "-"
          }
          value={summary ? formatPercent(summary.overall.win_rate, 1) : "-"}
          valueColor={summary ? getWinrateColor(summary.overall.win_rate) : undefined}
        />
        <HighlightCard
          title="Most played"
          subtitle={summary?.most_played ? summary.most_played.map.name : "-"}
          value={summary?.most_played ? `${summary.most_played.count} games` : "-"}
        />
        <HighlightCard
          title="Best map"
          subtitle={summary?.best ? `${summary.best.map.name} | ${summary.best.count} games` : "-"}
          value={summary?.best ? formatPercent(summary.best.win_rate, 0) : "-"}
          valueColor={summary?.best ? getWinrateColor(summary.best.win_rate) : undefined}
        />
        <HighlightCard
          title="Weakest map"
          subtitle={summary?.worst ? `${summary.worst.map.name} | ${summary.worst.count} games` : "-"}
          value={summary?.worst ? formatPercent(summary.worst.win_rate, 0) : "-"}
          valueColor={summary?.worst ? getWinrateColor(summary.worst.win_rate) : undefined}
        />
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="w-60">
            <SearchableImageSelect
              value={tournamentId ? String(tournamentId) : undefined}
              onValueChange={(val) => {
                setTournamentId(val ? Number(val) : undefined);
                pushParams({ [PAGE_KEY]: "1" }, false);
              }}
              options={tournamentOptions}
              placeholder="All tournaments"
              searchPlaceholder="Search tournament..."
              isLoading={tournamentsQuery.isLoading}
              disabled={tournamentsQuery.isLoading || tournamentsQuery.isError}
            />
          </div>

          <div className="relative md:w-[280px]">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
            <Input
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              type="search"
              placeholder="Search maps..."
              className="pl-8"
            />
          </div>

          <Select
            value={String(minCount)}
            onValueChange={(value) => pushParams({ [MIN_COUNT_KEY]: value }, true)}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Min games" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Min games: 1</SelectItem>
              <SelectItem value="3">Min games: 3</SelectItem>
              <SelectItem value="5">Min games: 5</SelectItem>
              <SelectItem value="10">Min games: 10</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={String(perPage)}
            onValueChange={(value) =>
              pushParams({ [PER_PAGE_KEY]: value === "-1" ? null : value }, true)
            }
          >
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Rows" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="15">Rows: 15</SelectItem>
              <SelectItem value="30">Rows: 30</SelectItem>
              <SelectItem value="-1">Rows: All</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={sort}
            onValueChange={(value) => pushParams({ [SORT_KEY]: value }, true)}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Sort" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="winrate">Sort: Winrate</SelectItem>
              <SelectItem value="count">Sort: Games</SelectItem>
              <SelectItem value="name">Sort: Name</SelectItem>
            </SelectContent>
          </Select>

          <Select value={order} onValueChange={(value) => pushParams({ [ORDER_KEY]: value }, true)}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Order" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="desc">Order: Descending</SelectItem>
              <SelectItem value="asc">Order: Ascending</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="text-xs text-muted-foreground">
          {mapsQueryResult.isFetching ? "Updating... " : null}
          Showing <span className="font-medium text-foreground tabular-nums">{showingCount}</span> of{" "}
          <span className="font-medium text-foreground tabular-nums">{totalCount}</span>
          {" "}maps | Sorted by {sortLabel.toLowerCase()}
        </div>
      </div>

      {error ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            {error instanceof Error ? error.message : "Failed to load maps."}
          </CardContent>
        </Card>
      ) : isLoading ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted-foreground">Loading maps...</CardContent>
        </Card>
      ) : (
        <>
          {/* Mobile */}
          <div className="md:hidden space-y-3">
            {(mapsData?.results ?? []).map((row: UserMapRead) => {
              const winrateColor = getWinrateColor(row.win_rate);
              return (
                <Card key={row.map.id} className="overflow-hidden">
                  <div className="relative h-28">
                    <Image
                      src={row.map.image_path}
                      alt={row.map.name}
                      fill
                      className="object-cover brightness-75"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-background/80 via-background/20 to-transparent" />
                    <div className="absolute bottom-3 left-3 right-3">
                      <div className="flex items-end justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-white truncate">{row.map.name}</div>
                          <div className="text-xs text-white/80">
                            {row.win}-{row.loss}-{row.draw} | {row.count} games
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="text-2xl font-bold tabular-nums" style={{ color: winrateColor }}>
                            {formatPercent(row.win_rate, 0)}
                          </div>
                          <div className="text-[11px] text-white/70">Winrate</div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <CardContent className="pt-4">
                    {row.hero_stats && row.hero_stats.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {row.hero_stats.map((hs) => {
                          const popoverKey = `m:${row.map.id}:${hs.hero.id}`;
                          return (
                            <HeroStatsChip
                              key={`${row.map.id}:${hs.hero.id}`}
                              heroStats={hs}
                              open={activeHeroPopoverKey === popoverKey}
                              onRequestOpen={() => openHeroPopover(popoverKey)}
                              onRequestClose={() => closeHeroPopover(popoverKey)}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">No hero data for this map.</div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Desktop */}
          <Card className="hidden md:block">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Maps Explorer</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Map</TableHead>
                    <TableHead>Heroes</TableHead>
                    <TableHead className="text-center">Winrate</TableHead>
                    <TableHead className="text-center">Record</TableHead>
                    <TableHead className="text-center">Games</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(mapsData?.results ?? []).map((row: UserMapRead) => {
                    const winrateColor = getWinrateColor(row.win_rate);
                    return (
                      <TableRow key={row.map.id}>
                        <TableCell>
                          <div className="flex items-center gap-3 min-w-0">
                            <div className="relative h-10 w-40 shrink-0 overflow-hidden rounded-md border">
                              <Image
                                src={row.map.image_path}
                                alt={row.map.name}
                                fill
                                className="object-cover brightness-75"
                              />
                              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-transparent to-background/70" />
                            </div>
                            <div className="min-w-0">
                              <div className="font-medium truncate">{row.map.name}</div>
                              {row.map.gamemode ? (
                                <div className="text-xs text-muted-foreground truncate">
                                  {row.map.gamemode.name}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          {row.hero_stats && row.hero_stats.length > 0 ? (
                            <div className="flex flex-wrap gap-2">
                              {row.hero_stats.map((hs) => {
                                const popoverKey = `d:${row.map.id}:${hs.hero.id}`;
                                return (
                                  <HeroStatsChip
                                    key={`${row.map.id}:${hs.hero.id}`}
                                    heroStats={hs}
                                    open={activeHeroPopoverKey === popoverKey}
                                    onRequestOpen={() => openHeroPopover(popoverKey)}
                                    onRequestClose={() => closeHeroPopover(popoverKey)}
                                  />
                                );
                              })}
                            </div>
                          ) : (
                            <div className="text-xs text-muted-foreground">-</div>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          <span className="font-semibold tabular-nums" style={{ color: winrateColor }}>
                            {formatPercent(row.win_rate, 0)}
                          </span>
                        </TableCell>
                        <TableCell className="text-center">
                          <span className="tabular-nums">
                            <span className="text-emerald-400">{row.win}</span>
                            <span className="text-muted-foreground">-</span>
                            <span className="text-red-400">{row.loss}</span>
                            <span className="text-muted-foreground">-</span>
                            <span className="text-slate-400">{row.draw}</span>
                          </span>
                        </TableCell>
                        <TableCell className="text-center tabular-nums">{row.count}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {perPage !== -1 && totalCount > perPage ? (
            <div className="pt-2">
              <PaginationWithLinks
                page={page}
                totalCount={totalCount}
                pageSize={perPage}
                pageSearchParam={PAGE_KEY}
              />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
