"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronsDown, ChevronsUp, ImagePlus, Scissors } from "lucide-react";
import Image from "next/image";

import { DataTable, createKebabColumn } from "@/components/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";

import {
  bandIconUrl,
  bandRangeLabel,
  bandSize,
  bandVerdict,
  type Action,
  type Band,
  type BandVerdict
} from "./draftReducer";

const VERDICT_TONE: Record<BandVerdict, "info" | "accent" | "warning"> = {
  renamed: "info",
  "band moved": "accent",
  new: "warning"
};

export interface DivisionsTableProps {
  bands: Band[];
  base: Band[];
  editable: boolean;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
  /** Opens the crest picker for the band at this index. */
  onPickIcon: (bandIndex: number) => void;
}

/**
 * The draft's divisions as a table (F12 ·3, Divisions view).
 *
 * Client-mode: the whole draft is in memory by definition, so paging, sorting
 * and search are the table's own business and no request follows an edit.
 *
 * The hi-fi reference put "3 RENAMED / BAND MOVED" in the players cell; those
 * are two different quantities and read as one broken number, so the diff verdict
 * gets its own column (IA §9).
 */
export function DivisionsTable({
  bands,
  base,
  editable,
  selectedSlug,
  onSelect,
  dispatch,
  onPickIcon
}: Readonly<DivisionsTableProps>) {
  const columns = useMemo<ColumnDef<Band>[]>(() => {
    const definitions: ColumnDef<Band>[] = [
      {
        id: "number",
        header: "#",
        size: 52,
        cell: ({ row }) => <span className="font-mono tabular-nums">{row.original.number}</span>
      },
      {
        id: "name",
        header: "Name",
        cell: ({ row }) => {
          const band = row.original;
          return (
            <div className="flex min-w-0 items-center gap-2">
              <Image
                src={bandIconUrl(band)}
                alt=""
                width={20}
                height={20}
                className="size-5 shrink-0"
                unoptimized
              />
              <InlineEditText
                value={band.name}
                label={`name of division ${band.number}`}
                canEdit={editable}
                textClassName="text-sm font-medium"
                onSave={(next) =>
                  dispatch({ type: "rename", bandIndex: band.number - 1, name: next })
                }
              />
              {band.icon_url === null ? (
                <StatusPill tone="neutral">borrows crest</StatusPill>
              ) : null}
            </div>
          );
        }
      },
      {
        id: "band",
        header: "OW band",
        cell: ({ row }) => <span className="font-mono text-sm">{bandRangeLabel(row.original)}</span>
      },
      {
        id: "ranks",
        header: "Ranks",
        size: 76,
        cell: ({ row }) => <span className="font-mono tabular-nums">{bandSize(row.original)}</span>
      },
      {
        id: "players",
        header: "Players",
        size: 90,
        cell: () => (
          <span
            className="text-muted-foreground"
            title="Player distribution per division is not exposed yet (backend gap G1)."
          >
            &mdash;
          </span>
        )
      },
      {
        id: "verdict",
        header: "vs base",
        size: 120,
        cell: ({ row }) => {
          const verdict = bandVerdict(base, row.original);
          if (verdict === null) return <span className="text-muted-foreground">&mdash;</span>;
          return <StatusPill tone={VERDICT_TONE[verdict]}>{verdict}</StatusPill>;
        }
      }
    ];

    if (!editable) return definitions;

    return [
      ...definitions,
      createKebabColumn<Band>(
        (band) => {
          const index = band.number - 1;
          return [
            {
              label: "Set crest…",
              icon: ImagePlus,
              onSelect: () => onPickIcon(index)
            },
            {
              label: "Merge into the division above",
              icon: ChevronsUp,
              hidden: index === 0,
              onSelect: () => dispatch({ type: "merge", bandIndex: index, into: "up" })
            },
            {
              label: "Merge into the division below",
              icon: ChevronsDown,
              hidden: index === bands.length - 1,
              onSelect: () => dispatch({ type: "merge", bandIndex: index, into: "down" })
            }
          ];
        },
        { rowLabel: (band) => band.name }
      )
    ];
  }, [bands.length, base, dispatch, editable, onPickIcon]);

  return (
    <div className="flex flex-col gap-2">
      <DataTable<Band>
        rows={bands}
        columns={columns}
        getRowId={(row) => row.slug}
        initialPageSize={25}
        inspectorId={selectedSlug}
        onRowClick={(row) => onSelect(row.original.slug)}
        emptyMessage="This draft has no divisions."
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {row.original.number}. {row.original.name}
            </p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {bandRangeLabel(row.original)} · {bandSize(row.original)} ranks
            </p>
          </div>
        )}
      />

      <p className="text-xs text-muted-foreground">
        Bands are contiguous by construction — raising one floor lowers its neighbour&apos;s
        ceiling, so a gap or an overlap cannot be entered.{" "}
        {editable ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => dispatch({ type: "splitWidest" })}
          >
            <Scissors aria-hidden className="size-4" />
            Split the widest
          </Button>
        ) : null}
      </p>
    </div>
  );
}
