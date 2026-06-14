"use client";

import React, { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  PaginationState,
  SortingState,
  useReactTable
} from "@tanstack/react-table";
import Image from "next/image";
import { Filter, Swords } from "lucide-react";

import tournamentService from "@/services/tournament.service";
import encounterService from "@/services/encounter.service";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { PaginationWithLinks } from "@/components/ui/pagination-with-links";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { MapRead } from "@/types/map.types";
import { Match, Score } from "@/types/encounter.types";

const getStageLabel = (match: Match) =>
  match.encounter?.stage_item?.name ?? match.encounter?.stage?.name ?? "Unassigned";

const columns: ColumnDef<Match>[] = [
  {
    accessorKey: "map",
    header: "Map",
    cell: ({ row }) => {
      const map: MapRead = row.getValue("map");
      return (
        <div className="flex items-center gap-3 px-3 py-2.5">
          <div className="relative h-12 w-40 shrink-0 overflow-hidden rounded-md">
            <Image
              src={map.image_path}
              alt={map.name}
              fill
              style={{ objectFit: "cover" }}
              className="brightness-75"
            />
          </div>
          <span className="text-sm font-medium text-white/90 whitespace-nowrap">{map.name}</span>
        </div>
      );
    }
  },
  {
    accessorKey: "tournament",
    header: "Tournament",
    cell: ({ row }) => (
      <div className="px-3 py-2.5">
        <span className="text-sm text-white/60">{row.original.encounter?.tournament.name}</span>
      </div>
    )
  },
  {
    accessorKey: "stage",
    header: "Stage",
    cell: ({ row }) => (
      <div className="px-3 py-2.5">
        <span className="inline-flex items-center rounded-full bg-white/[0.06] border border-white/[0.08] px-2 py-0.5 text-[11px] text-white/55">
          {getStageLabel(row.original)}
        </span>
      </div>
    )
  },
  {
    accessorKey: "name",
    header: "Match",
    cell: ({ row }) => (
      <div className="px-3 py-2.5">
        <span className="text-sm text-white/85">{row.original.home_team?.name}</span>
        <span className="text-sm text-white/30 mx-1.5">vs</span>
        <span className="text-sm text-white/85">{row.original.away_team?.name}</span>
      </div>
    )
  },
  {
    accessorKey: "score",
    header: "Score",
    cell: ({ row }) => {
      const score: Score = row.getValue("score");
      return (
        <div className="px-3 py-2.5">
          <span className="text-sm font-semibold tabular-nums text-white/85">
            {score.home}<span className="text-white/30 mx-0.5">–</span>{score.away}
          </span>
        </div>
      );
    }
  }
];

const MatchesPage = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [activeTournamentId, setActiveTournamentId] = useState<number | null>(null);
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [pagination, setPagination] = React.useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10
  });

  const { data: tournamentsData } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll()
  });

  const { data: matchesData, isLoading: isLoadingMatches } = useQuery({
    queryKey: ["matches", pagination.pageIndex],
    queryFn: () => encounterService.getAllMatches(pagination.pageIndex + 1, pagination.pageSize, "")
  });

  const table = useReactTable({
    data: matchesData?.results || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    rowCount: matchesData?.total || 0,
    onSortingChange: setSorting,
    state: { sorting, pagination },
    manualPagination: true
  });

  useEffect(() => {
    const newSearchParams = new URLSearchParams(searchParams);
    setPagination((prev) => ({
      ...prev,
      pageIndex: Number(newSearchParams.get("page")) - 1 || 0
    }));
    if (!newSearchParams.has("page")) {
      newSearchParams.set("page", "1");
      router.push(`${pathname}?${newSearchParams.toString()}`);
    }
  }, [pathname, router, searchParams]);

  const pushTournamentId = (newTournamentId: string) => {
    if (!searchParams) return;
    const newSearchParams = new URLSearchParams(searchParams);

    if (newTournamentId === "all") {
      newSearchParams.delete("tournamentId");
      setActiveTournamentId(null);
    } else {
      newSearchParams.set("tournamentId", String(newTournamentId));
      setActiveTournamentId(Number(newTournamentId));
    }

    router.push(`${pathname}?${newSearchParams.toString()}`);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Matches</h1>
          {matchesData && (
            <p className="mt-1 text-sm text-white/40">
              {matchesData.total.toLocaleString()} matches total
            </p>
          )}
        </div>

        {/* Filter */}
        <div className="flex items-center gap-2.5">
          <Filter className="h-3.5 w-3.5 text-white/30 shrink-0" />
          <Select
            value={activeTournamentId?.toString() ?? "all"}
            onValueChange={(value) => pushTournamentId(value)}
          >
            <SelectTrigger className="h-8 w-full sm:w-64 border-white/[0.07] bg-white/[0.02] text-sm text-white/80 shadow-none hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0">
              <SelectValue placeholder="All tournaments" />
            </SelectTrigger>
            <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
              <SelectItem value="all">All tournaments</SelectItem>
              <SelectGroup>
                {tournamentsData?.results.map((item) => (
                  <SelectItem key={item.id} value={item.id.toString()}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      {isLoadingMatches ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="rounded-xl border border-white/[0.07] overflow-hidden">
            <ScrollArea>
              <table className="w-full caption-bottom text-sm">
                <thead>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr key={headerGroup.id} className="border-b border-white/[0.06]">
                      {headerGroup.headers.map((header) => (
                        <th
                          key={header.id}
                          className="h-8 px-3 text-left text-[10px] uppercase tracking-wide text-white/35 font-semibold whitespace-nowrap"
                        >
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows?.length ? (
                    table.getRowModel().rows.map((row) => (
                      <tr
                        key={row.id}
                        onClick={() => router.push(`/matches/${row.original.id}`)}
                        className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.03] cursor-pointer transition-colors"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="p-0 align-middle">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td
                        colSpan={columns.length}
                        className="h-32 text-center align-middle"
                      >
                        <div className="flex flex-col items-center justify-center gap-2 text-white/25">
                          <Swords className="h-8 w-8" />
                          <p className="text-sm">No matches found.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </div>
          <PaginationWithLinks
            page={pagination.pageIndex + 1}
            totalCount={matchesData?.total || 0}
            pageSize={pagination.pageSize}
          />
        </div>
      )}
    </div>
  );
};

const MatchesPageWrapper = () => (
  <Suspense fallback={<div>Loading...</div>}>
    <MatchesPage />
  </Suspense>
);

export default MatchesPageWrapper;
