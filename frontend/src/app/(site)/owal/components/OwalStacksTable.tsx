"use client";

import React from "react";
import { OwalStack } from "@/types/tournament.types";
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
  useReactTable
} from "@tanstack/react-table";
import { useRouter } from "next/navigation";
import { CardContent, Card } from "@/components/ui/card";
import Link from "next/link";

const OwalStandingsTable = ({ data }: { data: OwalStack[] }) => {
  const columns: ColumnDef<OwalStack>[] = [
    {
      accessorKey: "user_1.name",
      id: "userName1",
      header: "Player One",
      cell: ({ row }) => {
        const userName = row.getValue<string>("userName1");

        return (
          <Link
            href={`/users/${userName.replace("#", "-")}`}
            className="text-left"
          >
            {userName.split("#")[0]}
          </Link>
        );
      }
    },
    {
      accessorKey: "user_2.name",
      id: "userName2",
      header: "Player Two",
      cell: ({ row }) => {
        const userName = row.getValue<string>("userName2");

        return (
          <Link
            href={`/users/${userName.replace("#", "-")}`}
            className="text-left"
          >
            {userName.split("#")[0]}
          </Link>
        );
      }
    },
    {
      accessorKey: "games",
      header: "Days",
      id: "games",
      cell: ({ row }) => <div>{row.getValue("games")}</div>
    },
    {
      accessorKey: "avg_position",
      header: "Average Placement",
      id: "avg_position",
      cell: ({ row }) => {
        const avgPosition = row.getValue<number>("avg_position");
        return <div>{avgPosition.toFixed(2)}</div>;
      }
    }
  ];

  const table = useReactTable({
    data: data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    rowCount: data.length
  });

  return (
    <Card className="w-[800px]">
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
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                  {row.getVisibleCells().map((cell) => {
                    // @ts-ignore
                    if (
                      cell.column.columnDef.header &&
                      cell.column?.columnDef?.id?.startsWith("day") &&
                      cell.column.columnDef.id !== "place"
                    ) {
                      return (
                        // @ts-ignore
                        <TableCell key={cell.id} className="text-center">
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
              ))
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
  );
};

export default OwalStandingsTable;
