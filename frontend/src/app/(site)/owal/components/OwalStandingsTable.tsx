"use client";

import React from "react";
import { OwalStanding, OwalStandings } from "@/types/tournament.types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { getWinrateColor } from "@/utils/colors";
import { CardContent, Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { DataTableSortButton } from "@/components/DataTableSortButton";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import Link from "next/link";

const getDayColor = (points: number) => {
  let color = {} as React.CSSProperties;
  if (points < 1.71) {
    color = { backgroundColor: "#f56565", color: "#121009" };
  }
  if (points > 3) {
    color = { backgroundColor: "#a86243" } as React.CSSProperties;
    if (points > 4) {
      color = { backgroundColor: "#99b0cc", color: "#121009" };
    }
    if (points > 5) {
      color = { backgroundColor: "#cbb765", color: "#121009" };
    }
  }
  return color;
};

const OwalStandingsTable = ({ data }: { data: OwalStandings }) => {
  const VIRTUALIZATION_THRESHOLD = 120;
  const [sorting, setSorting] = React.useState<SortingState>([
    {
      id: "place",
      desc: false
    }
  ]);
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [show3Plus, setShow3Plus] = React.useState(false);
  const parentRef = React.useRef<HTMLDivElement>(null);

  const days_columns = React.useMemo<ColumnDef<OwalStanding>[]>(
    () =>
      data.days.map((day) => ({
        id: `day_${day.id}`,
        accessorFn: (row) => (row.days[day.id.toString()] ? row.days[day.id.toString()].points : "-"),
        header: ({ column }) => (
          <DataTableSortButton column={column} label={day.name.split(" | ")[1]} />
        ),
        cell: ({ row, getValue }) => {
          const value = getValue<number | string>();
          if (value === "-") return <div>-</div>;

          const dayData = row.original.days[day.id.toString()] as
            | { points?: number; division?: number }
            | undefined;
          const dayDivision = dayData?.division ?? undefined;

          return (
            <div className="flex items-center justify-center gap-2">
              <span>{value as number}</span>
              {typeof dayDivision === "number" && (
                <PlayerDivisionIcon division={dayDivision} width={24} height={24} />
              )}
            </div>
          );
        }
      })),
    [data.days]
  );

  const columns = React.useMemo<ColumnDef<OwalStanding>[]>(
    () => [
      {
        accessorKey: "place",
        header: ({ column }) => {
          return <DataTableSortButton column={column} label={"Place"} />;
        },
        id: "place",
        accessorFn: (row) => row.place
      },
      {
        accessorKey: "user.name",
        id: "userName",
        header: "Player",
        cell: ({ row }) => {
          return (
            <div className="text-right">
              <Link href={`/users/${row.getValue<string>("userName").replace("#", "-")}`}>
                {row.getValue<string>("userName").split("#")[0]}
              </Link>
            </div>
          );
        }
      },
      {
        accessorKey: "role",
        id: "role",
        header: "Role",
        cell: ({ row }) => {
          return <div className="text-right">{row.getValue<string>("role")}</div>;
        }
      },
      {
        accessorKey: "division",
        id: "division",
        header: "Division",
        cell: ({ row }) => {
          return (
            <PlayerDivisionIcon
              division={row.getValue<number>("division")}
              width={32}
              height={32}
            />
          );
        }
      },
      ...days_columns,
      {
        accessorKey: "count_days",
        header: "Played",
        id: "count_days",
        cell: ({ row }) => <div>{row.getValue<number>("count_days")}</div>
      },
      {
        accessorKey: "best_3_days",
        id: "best_3_days",
        header: "TOTAL (best 3 days)",
        cell: ({ row }) => {
          return <div>{row.getValue<number>("best_3_days").toFixed(3)}</div>;
        }
      },
      {
        accessorKey: "avg_points",
        header: "Average",
        id: "avg_points",
        cell: ({ row }) => {
          return <div>{row.getValue<number>("avg_points").toFixed(3)}</div>;
        }
      },
      {
        accessorKey: "wins",
        header: "W",
        id: "wins",
        cell: ({ row }) => {
          return <div className="text-green-400">{row.getValue<number>("wins")}</div>;
        }
      },
      {
        accessorKey: "losses",
        header: "L",
        id: "losses",
        cell: ({ row }) => {
          return <div className="text-red-400">{row.getValue<number>("losses")}</div>;
        }
      },
      {
        accessorKey: "draws",
        header: "D",
        id: "draws",
        cell: ({ row }) => {
          return <div className="text-gray-400">{row.getValue<number>("draws")}</div>;
        }
      },
      {
        accessorKey: "win_rate",
        id: "win_rate",
        header: ({ column }) => {
          return <DataTableSortButton column={column} label={"Win ratio"} />;
        },
        cell: ({ row }) => {
          const winrate = row.getValue<number>("win_rate");
          return (
            <div style={{ color: getWinrateColor(winrate) }}>{(winrate * 100).toFixed(2)}%</div>
          );
        }
      }
    ],
    [days_columns]
  );

  const standingsData = React.useMemo(
    () => (show3Plus ? data.standings.filter((s) => s.count_days >= 3) : data.standings),
    [show3Plus, data.standings]
  );

  const table = useReactTable({
    data: standingsData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    rowCount: standingsData.length,
    onSortingChange: setSorting,
    state: {
      sorting,
      globalFilter
    },
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: (row, columnId, filterValue) => {
      return row.getValue<string>("userName").toLowerCase().includes(filterValue.toLowerCase());
    }
  });

  const rows = table.getRowModel().rows;
  const shouldVirtualize = rows.length > VIRTUALIZATION_THRESHOLD;

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48,
    overscan: 10
  });

  const virtualRows = shouldVirtualize ? rowVirtualizer.getVirtualItems() : [];
  const totalSize = shouldVirtualize ? rowVirtualizer.getTotalSize() : 0;
  const paddingTop = shouldVirtualize && virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    shouldVirtualize && virtualRows.length > 0 ? totalSize - virtualRows[virtualRows.length - 1].end : 0;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="sm:w-[300px] md:w-[200px] lg:w-[300px]">
          <Input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Search user..."
          />
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            id="only3plus"
            checked={show3Plus}
            onCheckedChange={(v) => setShow3Plus(v === true)}
          />
          <Label htmlFor="only3plus">Only 3+ days</Label>
        </div>
      </div>
      <div ref={parentRef} className="max-h-[70vh] overflow-auto">
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      return (
                        <TableHead className="text-center" key={header.id}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {rows.length ? (
                  <>
                    {paddingTop > 0 ? (
                      <TableRow>
                        <TableCell colSpan={columns.length} style={{ height: `${paddingTop}px` }} />
                      </TableRow>
                    ) : null}

                    {(shouldVirtualize
                      ? virtualRows.map((virtualRow) => rows[virtualRow.index])
                      : rows
                    ).map((row) => {
                      return (
                        <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                          {row.getVisibleCells().map((cell) => {
                            if (
                              cell.column.columnDef.header &&
                              cell.column?.columnDef?.id?.startsWith("day") &&
                              cell.column.columnDef.id !== "place"
                            ) {
                              return (
                                <TableCell
                                  key={cell.id}
                                  className="text-center"
                                  style={getDayColor(cell?.getValue() as number)}
                                >
                                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </TableCell>
                              );
                            }
                            // @ts-ignore
                            if (
                              cell.column.columnDef.header &&
                              cell.column.columnDef.id == "best_3_days"
                            ) {
                              return (
                                <TableCell key={cell.id} className="bg-gray-800 text-center">
                                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </TableCell>
                              );
                            }
                            return (
                              <TableCell className="text-center" key={cell.id}>
                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      );
                    })}

                    {paddingBottom > 0 ? (
                      <TableRow>
                        <TableCell colSpan={columns.length} style={{ height: `${paddingBottom}px` }} />
                      </TableRow>
                    ) : null}
                  </>
                ) : (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="h-24 text-center">
                      No results.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default OwalStandingsTable;
