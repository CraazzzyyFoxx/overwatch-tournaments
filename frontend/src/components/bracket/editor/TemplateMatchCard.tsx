"use client";

import { ArrowDown, ArrowUp, MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { RowButton } from "@/components/ui/row-button";
import { cn } from "@/lib/utils";

import { sourceLabel } from "@/lib/bracket/view";
import type { DuelSlot } from "@/lib/encounter/seats";

import { CARD_FOOTER, CARD_FRAME, MatchGutter } from "../MatchCard";
import { CARD_ROW_HEIGHT } from "../layout";
import type { DraftMatch } from "./templateDraft";

/** The output a click picked up, waiting for the slot it feeds. */
export interface ConnectSource {
  source: number;
  role: "winner" | "loser";
}

interface TemplateMatchCardProps {
  match: DraftMatch;
  /** Seeds no slot holds yet: everything the slot menu may offer. */
  availableSeeds: string[];
  /** A DE upper match that is not the final — the only kind that drops a loser. */
  showLoserPort: boolean;
  connecting: ConnectSource | null;
  onPort: (role: "winner" | "loser") => void;
  onConnect: (slot: DuelSlot) => void;
  onSeed: (slot: DuelSlot, seed: string) => void;
  onClear: (slot: DuelSlot) => void;
  onMove: (direction: -1 | 1) => void;
  onDelete: () => void;
}

/**
 * One match of the draft, as a wiring box: two slot rows that take a
 * connection or a seed, and `W`/`L` outputs that start one.
 *
 * Everything clickable is a `<button>`, which is also what keeps
 * `useBracketViewport` from reading a click on a port as the start of a pan.
 */
export function TemplateMatchCard({
  match,
  availableSeeds,
  showLoserPort,
  connecting,
  onPort,
  onConnect,
  onSeed,
  onClear,
  onMove,
  onDelete
}: Readonly<TemplateMatchCardProps>) {
  const t = useTranslations("bracketEditor");
  // A match cannot feed itself, so its own rows are never targets.
  const targeting = connecting !== null && connecting.source !== match.id;

  const slotRow = (slotNumber: DuelSlot) => {
    const slot = match.slots[slotNumber - 1] ?? null;
    // Named by TEMPLATE id, which is what the card's own gutter and the
    // validator's problems say — the view's "W M3" hints count matches in play
    // order instead, and the two numberings disagree on any custom layout.
    const label =
      slot?.seed ??
      (slot?.source_match != null
        ? `${sourceLabel(slot.source_position)} M${slot.source_match}`
        : t("empty"));
    // On screen the card's gutter says which match this row belongs to; an
    // accessible name has to carry it itself, so a listener hears
    // "M3 slot 1: L1" rather than a bare "L1".
    const name = t("slotLabel", { id: match.id, slot: slotNumber, state: slot === null ? t("empty").toLowerCase() : label });
    const rowClass = cn(
      "flex items-center justify-between gap-2 px-2.5 text-caption",
      slotNumber === 1 && "border-b border-[color:var(--aqt-border)]",
      slot === null
        ? "italic text-[color:var(--aqt-fg-faint)]"
        : "text-[color:var(--aqt-fg)]"
    );

    if (targeting) {
      return (
        <RowButton
          aria-label={`${name} — ${t("connectHere")}`}
          data-template-slot={`${match.id}-${slotNumber}`}
          data-connect-target=""
          className={cn(
            rowClass,
            "bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] ring-1 ring-inset ring-[color:var(--aqt-teal)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_24%,transparent)]"
          )}
          style={{ height: CARD_ROW_HEIGHT }}
          onClick={() => onConnect(slotNumber)}
        >
          <span className="truncate">{label}</span>
          <span className="shrink-0 text-label uppercase text-[color:var(--aqt-teal)]">{t("drop")}</span>
        </RowButton>
      );
    }

    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <RowButton
            aria-label={name}
            data-template-slot={`${match.id}-${slotNumber}`}
            className={rowClass}
            style={{ height: CARD_ROW_HEIGHT }}
          >
            <span className="truncate">{label}</span>
          </RowButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-64 overflow-y-auto">
          {availableSeeds.map((seed) => (
            <DropdownMenuItem key={seed} onSelect={() => onSeed(slotNumber, seed)}>
              {seed}
            </DropdownMenuItem>
          ))}
          <DropdownMenuItem onSelect={() => onClear(slotNumber)}>{t("clear")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className={cn(CARD_FRAME, "border-[color:var(--aqt-border)]")}>
      <MatchGutter number={match.id} />

      <div className="flex min-w-0 flex-1 flex-col">
        {slotRow(1)}
        {slotRow(2)}

        <div className={cn(CARD_FOOTER, "flex-1")}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                className="text-[color:var(--aqt-fg-muted)]"
                aria-label={t("matchActions", { id: match.id })}
              >
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => onMove(-1)}>
                <ArrowUp className="size-4" aria-hidden />
                {t("moveUp")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onMove(1)}>
                <ArrowDown className="size-4" aria-hidden />
                {t("moveDown")}
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 className="size-4" aria-hidden />
                {t("delete")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* The outputs, on the edge the connectors leave from. */}
      <div className="flex shrink-0 flex-col items-center justify-center gap-1 border-l border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-1">
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          data-template-port={`${match.id}-winner`}
          aria-pressed={connecting?.source === match.id && connecting.role === "winner"}
          aria-label={t("connectWinner", { id: match.id })}
          title={t("connectWinner", { id: match.id })}
          className={cn(
            connecting?.source === match.id &&
              connecting.role === "winner" &&
              "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_22%,transparent)] text-[color:var(--aqt-teal)]"
          )}
          onClick={() => onPort("winner")}
        >
          W
        </Button>
        {showLoserPort ? (
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            data-template-port={`${match.id}-loser`}
            aria-pressed={connecting?.source === match.id && connecting.role === "loser"}
            aria-label={t("connectLoser", { id: match.id })}
            title={t("connectLoser", { id: match.id })}
            className={cn(
              connecting?.source === match.id &&
                connecting.role === "loser" &&
                "border-[color:var(--aqt-blue)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] text-[color:var(--aqt-blue)]"
            )}
            onClick={() => onPort("loser")}
          >
            L
          </Button>
        ) : null}
      </div>
    </div>
  );
}
