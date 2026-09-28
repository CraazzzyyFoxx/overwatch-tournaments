"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronsDown, ChevronsUp, ImagePlus, Scissors, Unlink } from "lucide-react";
import Image from "next/image";

import { DataTable, createKebabColumn } from "@/components/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import {
  bandIconUrl,
  bandVerdict,
  floorError,
  owRangeLabel,
  owSize,
  rankRangeLabel,
  type Action,
  type Band,
  type BandVerdict,
  type Scale
} from "./draftReducer";
import { OwRangePicker } from "./OwRangePicker";

const VERDICT_TONE: Record<BandVerdict, "info" | "accent" | "warning"> = {
  renamed: "info",
  relinked: "info",
  "range moved": "accent",
  new: "warning"
};

export interface DivisionsTableProps {
  bands: Band[];
  base: Band[];
  scale: Scale;
  editable: boolean;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
  /** Opens the crest picker for the band at this index. */
  onPickIcon: (bandIndex: number) => void;
  /** Asks to switch the scale; the editor confirms the switch that rewrites ranges. */
  onScaleChange: (scale: Scale) => void;
  /** Every OW rank and every division linked — the precondition for following the ladder. */
  canFollowLadder: boolean;
}

/**
 * The draft's divisions as a table (F12 ·3, Divisions view).
 *
 * Two range columns because a division has two: its span on the workspace's
 * rank scale, and the OW ranks that land in it. On the ladder scale both come
 * from the ladder and are read-only here; on a custom scale the floor is typed
 * and the OW run is picked per division.
 */
export function DivisionsTable({
  bands,
  base,
  scale,
  editable,
  selectedSlug,
  onSelect,
  dispatch,
  onPickIcon,
  onScaleChange,
  canFollowLadder
}: Readonly<DivisionsTableProps>) {
  const custom = scale === "custom";

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
                className="size-5 shrink-0 object-contain"
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
        id: "range",
        header: "Rank range",
        size: 150,
        cell: ({ row }) =>
          custom && editable ? (
            <FloorField bands={bands} bandIndex={row.original.number - 1} dispatch={dispatch} />
          ) : (
            <span className="font-mono text-sm tabular-nums">{rankRangeLabel(row.original)}</span>
          )
      },
      {
        id: "ow",
        header: "OW ranks",
        cell: ({ row }) => {
          const band = row.original;
          if (custom && editable) {
            return (
              <OwRangePicker
                bands={bands}
                bandIndex={band.number - 1}
                onLink={(from, to) =>
                  dispatch({ type: "link", bandIndex: band.number - 1, from, to })
                }
                onUnlink={() => dispatch({ type: "unlink", bandIndex: band.number - 1 })}
              />
            );
          }
          return (
            <span className="font-mono text-sm">
              <span className={band.ow ? undefined : "text-warning"}>{owRangeLabel(band)}</span>
              {band.ow ? (
                <span className="ml-1.5 text-xs text-muted-foreground">· {owSize(band)}</span>
              ) : null}
            </span>
          );
        }
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
          const splittable = custom
            ? band.rankMax === null || band.rankMax > band.rankMin
            : owSize(band) >= 2;
          return [
            {
              label: "Set crest…",
              icon: ImagePlus,
              onSelect: () => onPickIcon(index)
            },
            {
              label: "Split in two",
              icon: Scissors,
              hidden: !splittable,
              onSelect: () => dispatch({ type: "split", bandIndex: index })
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
            },
            {
              label: "Unlink OW ranks",
              icon: Unlink,
              hidden: !custom || band.ow === null,
              onSelect: () => dispatch({ type: "unlink", bandIndex: index })
            }
          ];
        },
        { rowLabel: (band) => band.name }
      )
    ];
  }, [bands, base, custom, dispatch, editable, onPickIcon]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-xl border border-border bg-card px-3 py-2">
        <div className="flex min-w-0 max-w-prose flex-col gap-0.5">
          <span className={EYEBROW_CLASS}>Rank scale</span>
          <p className="text-xs text-muted-foreground">
            {custom
              ? "Floors are typed; each ceiling is the floor above minus one. OW ranks are linked per division."
              : "Rank ranges are the OW ladder's own values, so cutting the ladder moves both at once."}
            {custom && editable && !canFollowLadder
              ? " To follow the ladder, link every OW rank and every division first."
              : null}
          </p>
        </div>
        <ToggleGroup
          type="single"
          variant="pill"
          size="sm"
          value={scale}
          onValueChange={(next) => onScaleChange(next as Scale)}
          aria-label="Rank scale"
        >
          <ToggleGroupItem value="ladder" disabled={!editable || (custom && !canFollowLadder)}>
            Follow OW ladder
          </ToggleGroupItem>
          <ToggleGroupItem value="custom" disabled={!editable}>
            Custom
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      <DataTable<Band>
        rows={bands}
        columns={columns}
        getRowId={(row) => row.slug}
        initialPageSize={50}
        inspectorId={selectedSlug}
        onRowClick={(row) => onSelect(row.original.slug)}
        emptyMessage="This draft has no divisions."
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {row.original.number}. {row.original.name}
            </p>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {rankRangeLabel(row.original)} · {owRangeLabel(row.original)}
            </p>
          </div>
        )}
      />

      <p className="text-xs text-muted-foreground">
        {custom
          ? "A floor must sit between its neighbours' floors, so native ranges cannot overlap. OW runs stay in division order: taking ranks from a neighbour shortens it."
          : "Bands are contiguous by construction — moving one boundary moves both neighbours, so a gap or an overlap cannot be entered."}
      </p>
    </div>
  );
}

/** A custom-scale floor, committed on Enter or blur and refused with the reason when it would overlap a neighbour. */
function FloorField({
  bands,
  bandIndex,
  dispatch
}: Readonly<{ bands: Band[]; bandIndex: number; dispatch: (action: Action) => void }>) {
  const band = bands[bandIndex];
  const [draft, setDraft] = useState<string | null>(null);
  const error = draft === null ? null : floorError(bands, bandIndex, draft);

  const commit = () => {
    if (draft === null || error !== null) return;
    dispatch({ type: "setFloor", bandIndex, rankMin: Number(draft) });
    setDraft(null);
  };

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 font-mono text-sm tabular-nums">
        <Input
          inputMode="numeric"
          aria-label={`Floor of ${band.name}`}
          aria-invalid={error ? true : undefined}
          value={draft ?? String(band.rankMin)}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setDraft(null);
            }
          }}
          className="h-7 w-20 px-1.5 font-mono tabular-nums aria-invalid:border-destructive"
        />
        <span className="text-muted-foreground">&ndash; {band.rankMax ?? "\u221e"}</span>
      </div>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : null}
    </div>
  );
}
