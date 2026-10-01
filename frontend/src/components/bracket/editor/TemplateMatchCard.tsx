"use client";

import { ArrowDown, ArrowUp, MoreHorizontal, Trash2 } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { CARD_ROW_HEIGHT, GUTTER_WIDTH, type Side } from "../layout";
import type { DraftMatch } from "./templateDraft";

/** The output a click picked up, waiting for the slot it feeds. */
export interface ConnectSource {
  source: number;
  role: "winner" | "loser";
}

const PORT_BUTTON =
  "flex h-5 w-5 items-center justify-center rounded border text-[10px] font-bold leading-none transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";

interface TemplateMatchCardProps {
  match: DraftMatch;
  /** Seeds no slot holds yet: everything the slot menu may offer. */
  availableSeeds: string[];
  /** A DE upper match that is not the final — the only kind that drops a loser. */
  showLoserPort: boolean;
  connecting: ConnectSource | null;
  onPort: (role: "winner" | "loser") => void;
  onConnect: (slot: Side) => void;
  onSeed: (slot: Side, seed: string) => void;
  onClear: (slot: Side) => void;
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
  // A match cannot feed itself, so its own rows are never targets.
  const targeting = connecting !== null && connecting.source !== match.id;

  const slotRow = (side: Side) => {
    const slot = match[side];
    // Named by TEMPLATE id, which is what the card's own gutter and the
    // validator's problems say — the view's "W M3" hints count matches in play
    // order instead, and the two numberings disagree on any custom layout.
    const label =
      slot?.seed ??
      (slot?.winner_of != null
        ? `W M${slot.winner_of}`
        : slot?.loser_of != null
          ? `L M${slot.loser_of}`
          : "Empty");
    // On screen the card's gutter says which match this row belongs to; an
    // accessible name has to carry it itself, so a listener hears
    // "M3 home: L1" rather than a bare "L1".
    const name = `M${match.id} ${side}: ${slot === null ? "empty" : label}`;
    const rowClass = cn(
      "flex w-full items-center justify-between gap-2 px-2.5 text-left text-caption transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]",
      side === "home" && "border-b border-[color:var(--aqt-border)]",
      slot === null
        ? "italic text-[color:var(--aqt-fg-faint)]"
        : "text-[color:var(--aqt-fg)]"
    );

    if (targeting) {
      return (
        <button
          type="button"
          aria-label={`${name} — connect here`}
          data-template-slot={`${match.id}-${side}`}
          data-connect-target=""
          className={cn(
            rowClass,
            "bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] ring-1 ring-inset ring-[color:var(--aqt-teal)]"
          )}
          style={{ height: CARD_ROW_HEIGHT }}
          onClick={() => onConnect(side)}
        >
          <span className="truncate">{label}</span>
          <span className="shrink-0 text-label uppercase text-[color:var(--aqt-teal)]">drop</span>
        </button>
      );
    }

    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={name}
            data-template-slot={`${match.id}-${side}`}
            className={cn(rowClass, "hover:bg-[color:var(--aqt-overlay-3)]")}
            style={{ height: CARD_ROW_HEIGHT }}
          >
            <span className="truncate">{label}</span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-64 overflow-y-auto">
          {availableSeeds.map((seed) => (
            <DropdownMenuItem key={seed} onSelect={() => onSeed(side, seed)}>
              {seed}
            </DropdownMenuItem>
          ))}
          <DropdownMenuItem onSelect={() => onClear(side)}>Clear</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  return (
    <div className="relative flex h-full overflow-hidden rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] shadow-[0_10px_24px_rgba(0,0,0,0.28)]">
      <div
        className="flex shrink-0 flex-col items-center justify-center gap-0.5 border-r border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] leading-none text-[color:var(--aqt-fg-muted)]"
        style={{ width: GUTTER_WIDTH }}
      >
        <span className="text-[9px] font-semibold tracking-label opacity-70">M</span>
        <span className="text-caption font-bold tabular-nums">{match.id}</span>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {slotRow("home")}
        {slotRow("away")}

        <div className="flex flex-1 items-center justify-between gap-1.5 border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-1.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Match ${match.id} actions`}
                className="flex items-center justify-center rounded p-0.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              >
                <MoreHorizontal className="size-3.5" aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => onMove(-1)}>
                <ArrowUp className="size-4" aria-hidden />
                Move up
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onMove(1)}>
                <ArrowDown className="size-4" aria-hidden />
                Move down
              </DropdownMenuItem>
              <DropdownMenuItem className="text-danger focus:text-danger" onSelect={onDelete}>
                <Trash2 className="size-4" aria-hidden />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* The outputs, on the edge the connectors leave from. */}
      <div className="flex shrink-0 flex-col items-center justify-center gap-1 border-l border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-1">
        <button
          type="button"
          data-template-port={`${match.id}-winner`}
          aria-pressed={connecting?.source === match.id && connecting.role === "winner"}
          aria-label={`Connect winner of M${match.id}`}
          title={`Connect winner of M${match.id}`}
          className={cn(
            PORT_BUTTON,
            connecting?.source === match.id && connecting.role === "winner"
              ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_22%,transparent)] text-[color:var(--aqt-teal)]"
              : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
          )}
          onClick={() => onPort("winner")}
        >
          W
        </button>
        {showLoserPort ? (
          <button
            type="button"
            data-template-port={`${match.id}-loser`}
            aria-pressed={connecting?.source === match.id && connecting.role === "loser"}
            aria-label={`Connect loser of M${match.id}`}
            title={`Connect loser of M${match.id}`}
            className={cn(
              PORT_BUTTON,
              connecting?.source === match.id && connecting.role === "loser"
                ? "border-[color:var(--aqt-blue)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] text-[color:var(--aqt-blue)]"
                : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
            )}
            onClick={() => onPort("loser")}
          >
            L
          </button>
        ) : null}
      </div>
    </div>
  );
}
