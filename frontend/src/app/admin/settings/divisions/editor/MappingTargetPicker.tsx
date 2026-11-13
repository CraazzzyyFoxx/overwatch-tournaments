"use client";

import { useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@craazzzyyfoxx/admin-kit/ui/popover";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { cn } from "@/lib/utils";

import { overlapRange, type MappingChoice, type MappingRow, type MappingTarget } from "./autoMap";
import { rankRangeLabel, type Band } from "./draftReducer";

export interface MappingTargetPickerProps {
  row: MappingRow;
  bands: Band[];
  target: MappingTarget | null;
  /** `null` goes back to the automatic mapping. */
  onChange: (choice: MappingChoice | null) => void;
}

/** Names a target: "38. Bronze 3", plus "· over 36–40" when the players spread over a range. */
export function useTargetSummary() {
  const t = useTranslations("adminSettings.divisions.mapping");
  return (target: MappingTarget | null): string => {
    if (!target) return t("nothingChosen");
    const landing = `${target.primary.number}. ${target.primary.name}`;
    if (target.range.length === 1) return landing;
    return t("spreadSummary", { landing, from: target.range[0].number, to: target.range.at(-1)!.number });
  };
}

/**
 * Where one old division's players go in the draft: a range of divisions they
 * spread over, and the one they land in.
 *
 * Click a division to send the players there alone; click a second one to
 * spread them over every division between the two. The dot on a row of the
 * range moves where they land. A SPLIT row opens with its tied divisions
 * proposed, so resolving it is one click on a dot.
 */
export function MappingTargetPicker({ row, bands, target, onChange }: Readonly<MappingTargetPickerProps>) {
  const t = useTranslations("adminSettings.divisions.mapping");
  const targetSummary = useTargetSummary();
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<number | null>(null);
  const focusRef = useRef<HTMLButtonElement>(null);
  const name = row.source.name;

  // The range drawn: the target's, else the tie a SPLIT row asks to resolve.
  const shown = target?.range ?? overlapRange(row);
  const from = shown.length > 0 ? bands.findIndex((band) => band.slug === shown[0].slug) : -1;
  const to = from === -1 ? -1 : from + shown.length - 1;
  const proposed = target === null && shown.length > 1;
  const focusIndex = target ? bands.findIndex((band) => band.slug === target.primary.slug) : from;

  const toggle = (next: boolean) => {
    setOpen(next);
    if (!next) setAnchor(null);
  };

  const pick = (index: number) => {
    const band = bands[index];
    if (band.id === undefined) return;
    const anchored = anchor === null ? undefined : bands[anchor];
    if (anchored?.id === undefined || anchor === index) {
      onChange({ targets: [band.id], primary: band.id });
      setAnchor(anchor === index ? null : index);
      return;
    }
    onChange({ targets: [anchored.id, band.id], primary: anchored.id });
    setAnchor(null);
  };

  const land = (index: number) => {
    const ids = [bands[from]?.id, bands[to]?.id, bands[index]?.id];
    if (ids.some((id) => id === undefined)) return;
    onChange({ targets: [ids[0]!, ids[1]!], primary: ids[2]! });
    setAnchor(null);
  };

  const hint =
    anchor !== null
      ? t("spreadHint", { name })
      : proposed
        ? t("tieHint")
        : t("chooseHint");

  const note = !target
    ? null
    : target.range.length === 1
      ? t("everyPlayer", { name, target: target.primary.name })
      : t(target.byOverlap ? "overlapShares" : "evenShares");

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={t("targetLabel", { name, summary: targetSummary(target) })}
          className="w-full min-w-56 justify-between gap-2 px-2"
        >
          {target ? (
            <span className="flex min-w-0 items-baseline gap-1.5">
              <span className="truncate">
                {target.primary.number}. {target.primary.name}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {target.range.length > 1
                  ? t("over", { from: target.range[0].number, to: target.range.at(-1)!.number })
                  : rankRangeLabel(target.primary)}
              </span>
            </span>
          ) : (
            <span className="text-warning">{t("chooseTarget")}</span>
          )}
          <ChevronDown aria-hidden className="size-3 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[26rem] p-0"
        aria-label={t("targetDivisions", { name })}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          focusRef.current?.focus();
        }}
      >
        <div className="border-b border-border px-3 py-2">
          <p className="text-sm font-medium">
            {name} <span className="text-xs tabular-nums text-muted-foreground">{rankRangeLabel(row.source)}</span>
          </p>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {hint}
          </p>
        </div>

        <ol className="max-h-80 overflow-y-auto p-1">
          {bands.map((band, index) => {
            const inRange = index >= from && index <= to;
            const landing = target?.primary.slug === band.slug;
            const share = inRange
              ? target
                ? target.weights[index - from]
                : row.candidates.find((candidate) => candidate.band.slug === band.slug)?.weight
              : undefined;
            return (
              <li
                key={band.slug}
                className={cn(
                  "flex items-center gap-1 rounded-md border",
                  index === anchor
                    ? "border-primary"
                    : proposed && inRange
                      ? "border-dashed border-warning/60"
                      : "border-transparent",
                  inRange && !proposed && "bg-primary/10"
                )}
              >
                <RowButton
                  ref={index === focusIndex ? focusRef : undefined}
                  onClick={() => pick(index)}
                  className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm"
                >
                  <span className="w-6 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                    {band.number}
                  </span>
                  <span className={cn("min-w-0 flex-1 truncate", landing && "font-semibold")}>
                    {band.name}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {rankRangeLabel(band)}
                  </span>
                </RowButton>
                <span
                  className={cn(
                    "w-10 shrink-0 text-right text-xs tabular-nums",
                    target ? "text-foreground" : "text-muted-foreground"
                  )}
                >
                  {share === undefined ? null : `${Math.round(share * 100)}%`}
                </span>
                {inRange && shown.length > 1 ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-pressed={landing}
                    aria-label={t("playersLand", { source: name, target: band.name })}
                    title={t("playersLand", { source: name, target: band.name })}
                    onClick={() => land(index)}
                    className="mr-1 shrink-0 rounded-full"
                  >
                    <span
                      className={cn(
                        "size-2.5 rounded-full border",
                        landing ? "border-primary bg-primary" : "border-muted-foreground"
                      )}
                    />
                  </Button>
                ) : (
                  <span aria-hidden className="mr-1 size-5 shrink-0" />
                )}
              </li>
            );
          })}
        </ol>

        <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
          <p className="min-w-0 text-xs text-muted-foreground">{note ?? t("nothingChosen")}</p>
          {row.kind === "auto" && target?.manual ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 px-2"
              onClick={() => {
                onChange(null);
                setAnchor(null);
              }}
            >
              {t("automatic")}
            </Button>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
