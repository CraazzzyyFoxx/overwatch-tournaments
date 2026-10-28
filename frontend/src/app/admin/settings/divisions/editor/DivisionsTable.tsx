"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronsDown, ChevronsUp, ImagePlus, Scissors, Unlink } from "lucide-react";
import Image from "@/components/ui/image";
import { useTranslations } from "next-intl";

import { DataTable, createKebabColumn } from "@/components/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadAdminUI } from "@/disciplines/registry/admin";
import type { DisciplineCapabilities } from "@/types/discipline.types";

import {
  bandIconUrl,
  floorError,
  ladderOwners,
  nativeRangeLabel,
  nativeSize,
  rankRangeLabel,
  type Action,
  type Band,
  type Ladder,
  type Scale
} from "./draftReducer";

export interface DivisionsTableProps {
  bands: Band[];
  scale: Scale;
  /** The grid's own discipline: the native-rank editor slot is that game's, never another's. */
  discipline: string;
  capabilities: DisciplineCapabilities;
  /** The discipline's native ladder; `null` when it has none (no native column, no ladder scale). */
  ladder: Ladder | null;
  /** The game's short name ("OW") the native column and the ladder scale are named by. */
  game: string;
  editable: boolean;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  dispatch: (action: Action) => void;
  /** Opens the crest picker for the band at this index. */
  onPickIcon: (bandIndex: number) => void;
  /** Asks to switch the scale; the editor confirms the switch that rewrites ranges. */
  onScaleChange: (scale: Scale) => void;
  /** Every native rank and every division linked — the precondition for following the ladder. */
  canFollowLadder: boolean;
}

/**
 * The draft's divisions as a table (F12 ·3, Divisions view).
 *
 * Two range columns because a division has two: its span on the workspace's
 * rank scale, and the native ranks that land in it. On the ladder scale both come
 * from the ladder and are read-only here; on a custom scale the floor is typed
 * and the native run is picked per division.
 */
export function DivisionsTable({
  bands,
  scale,
  discipline,
  capabilities,
  ladder,
  game,
  editable,
  selectedSlug,
  onSelect,
  dispatch,
  onPickIcon,
  onScaleChange,
  canFollowLadder
}: Readonly<DivisionsTableProps>) {
  const t = useTranslations("adminSettings.divisions");
  const custom = scale === "custom";
  // Divisions without a crest of their own: borrowing the ladder's, or (no ladder) refused by the server.
  const crestless = bands.filter((band) => band.icon_url === null).length;
  // A switch only where both sides are reachable: leaving the ladder always is, returning needs full links.
  const scaleChoice = ladder !== null && editable && (!custom || canFollowLadder);

  const columns = useMemo<ColumnDef<Band>[]>(() => {
    const definitions: ColumnDef<Band>[] = [
      {
        id: "number",
        header: "#",
        size: 52,
        cell: ({ row }) => <span className="tabular-nums">{row.original.number}</span>
      },
      {
        id: "name",
        header: t("table.name"),
        cell: ({ row }) => {
          const band = row.original;
          const crest = bandIconUrl(ladder, band);
          const crestNote = band.icon_url === null
            ? t(ladder ? "table.borrowsCrest" : "table.crestRequired")
            : undefined;
          return (
            <div className="flex min-w-0 items-center gap-2">
              {crest ? (
                <Image
                  src={crest}
                  alt={crestNote ?? ""}
                  title={crestNote}
                  width={20}
                  height={20}
                  className="size-5 shrink-0 object-contain"
                  unoptimized
                />
              ) : (
                <span
                  role="img"
                  aria-label={crestNote}
                  title={crestNote}
                  className="size-5 shrink-0 rounded border border-dashed border-border"
                />
              )}
              <InlineEditText
                value={band.name}
                label={t("table.divisionName", { number: band.number })}
                canEdit={editable}
                textClassName="text-sm font-medium"
                onSave={(next) =>
                  dispatch({ type: "rename", bandIndex: band.number - 1, name: next })
                }
              />
            </div>
          );
        }
      },
      {
        id: "range",
        header: t("table.rankRange"),
        size: 150,
        cell: ({ row }) =>
          custom && editable ? (
            <FloorField bands={bands} bandIndex={row.original.number - 1} dispatch={dispatch} />
          ) : (
            <span className="text-sm tabular-nums">{rankRangeLabel(row.original)}</span>
          )
      },
      ...(ladder
        ? [
            {
              id: "native",
              header: t("table.owRanks", { game }),
              cell: ({ row }) => {
                const band = row.original;
                if (custom && editable) {
                  return (
                    <DisciplineWidget
                      discipline={discipline}
                      load={loadAdminUI}
                      slot="nativeRankEditor"
                      capabilities={capabilities}
                      requires="native_ladder"
                      props={{
                        ladder: ladder.ranks,
                        value: band.native,
                        owners: ladderOwners(ladder, bands).map((owner) =>
                          owner === null ? null : bands[owner].name
                        ),
                        label: band.name,
                        onChange: (next) =>
                          dispatch(
                            next
                              ? { type: "link", bandIndex: band.number - 1, from: next.from, to: next.to }
                              : { type: "unlink", bandIndex: band.number - 1 }
                          )
                      }}
                      fallback={null}
                    />
                  );
                }
                return (
                  <span className="text-sm">
                    <span className={band.native ? undefined : "text-warning"}>
                      {nativeRangeLabel(ladder, band) ?? t("ladder.notLinked")}
                    </span>
                    {band.native ? (
                      <span className="ml-1.5 text-xs text-muted-foreground">· {nativeSize(band)}</span>
                    ) : null}
                  </span>
                );
              }
            } satisfies ColumnDef<Band>
          ]
        : []),
    ];

    if (!editable) return definitions;

    return [
      ...definitions,
      createKebabColumn<Band>(
        (band) => {
          const index = band.number - 1;
          const splittable = custom
            ? band.rankMax === null || band.rankMax > band.rankMin
            : nativeSize(band) >= 2;
          return [
            {
              label: t("table.setCrest"),
              icon: ImagePlus,
              onSelect: () => onPickIcon(index)
            },
            {
              label: t("table.split"),
              icon: Scissors,
              hidden: !splittable,
              onSelect: () => dispatch({ type: "split", bandIndex: index })
            },
            {
              label: t("table.mergeAbove"),
              icon: ChevronsUp,
              hidden: index === 0,
              onSelect: () => dispatch({ type: "merge", bandIndex: index, into: "up" })
            },
            {
              label: t("table.mergeBelow"),
              icon: ChevronsDown,
              hidden: index === bands.length - 1,
              onSelect: () => dispatch({ type: "merge", bandIndex: index, into: "down" })
            },
            {
              label: t("table.unlink"),
              icon: Unlink,
              hidden: !custom || band.native === null,
              onSelect: () => dispatch({ type: "unlink", bandIndex: index })
            }
          ];
        },
        { rowLabel: (band) => band.name }
      )
    ];
  }, [bands, capabilities, custom, discipline, dispatch, editable, game, ladder, onPickIcon, t]);

  return (
    <div className="flex flex-col gap-3">
      <Card className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-3 py-2">
        <div className="flex min-w-0 max-w-prose flex-col gap-0.5">
          <span className={eyebrowClass("muted")}>{t("table.rankScale")}</span>
          <p className="text-xs text-muted-foreground">
            {custom
              ? t("table.customScaleHint")
              : t("table.ladderScaleHint")}
            {ladder && custom && editable && !canFollowLadder
              ? ` ${t("table.followLadderHint")}`
              : null}
          </p>
        </div>
        {scaleChoice ? (
          <ToggleGroup
            variant="pill"
            size="sm"
            value={scale}
            onValueChange={(next) => onScaleChange(next as Scale)}
            aria-label={t("table.rankScale")}
          >
            <ToggleGroupItem value="ladder">{t("table.followLadder", { game })}</ToggleGroupItem>
            <ToggleGroupItem value="custom">{t("table.custom")}</ToggleGroupItem>
          </ToggleGroup>
        ) : null}
      </Card>

      <DataTable<Band>
        rows={bands}
        columns={columns}
        getRowId={(row) => row.slug}
        initialPageSize={50}
        inspectorId={selectedSlug}
        onRowClick={(row) => onSelect(row.original.slug)}
        emptyMessage={t("table.empty")}
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {row.original.number}. {row.original.name}
            </p>
            <p className="truncate text-xs tabular-nums text-muted-foreground">
              {rankRangeLabel(row.original)}
              {ladder ? ` · ${nativeRangeLabel(ladder, row.original) ?? t("ladder.notLinked")}` : null}
            </p>
          </div>
        )}
      />

      <p className="text-xs text-muted-foreground">
        {custom
          ? t("table.customScaleFooter")
          : t("table.ladderScaleFooter")}
      </p>
      {crestless > 0 ? (
        <p className={ladder ? "text-xs text-muted-foreground" : "text-xs text-warning"}>
          {t(ladder ? "impactChecks.crestsSome" : "impactChecks.crestsRequired", { count: crestless })}
        </p>
      ) : null}
    </div>
  );
}

/** A custom-scale floor, committed on Enter or blur and refused with the reason when it would overlap a neighbour. */
function FloorField({
  bands,
  bandIndex,
  dispatch
}: Readonly<{ bands: Band[]; bandIndex: number; dispatch: (action: Action) => void }>) {
  const t = useTranslations("adminSettings.divisions");
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
      <div className="flex items-center gap-1.5 text-sm tabular-nums">
        <Input
          inputMode="numeric"
          aria-label={t("table.floor", { name: band.name })}
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
          size="sm"
          className="h-7 w-20 tabular-nums"
        />
        <span className="text-muted-foreground">&ndash; {band.rankMax ?? "\u221e"}</span>
      </div>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {error.code === "notInteger"
            ? t("table.floorErrors.notInteger")
            : t(`table.floorErrors.${error.code}`, { name: error.name, rankMin: error.rankMin })}
        </span>
      ) : null}
    </div>
  );
}
