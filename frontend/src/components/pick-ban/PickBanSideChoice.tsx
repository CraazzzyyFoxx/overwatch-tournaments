"use client";

import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import type { PickBanStartingSides } from "@/types/tournament.types";

import type { PickBanSeat } from "./pick-ban-model";

/**
 * A `side_pick` step's choice: one toggle per side of the game, chosen by its zero-based index into
 * `state.sides` — the wire value, so index 0 is a real choice. Native buttons carry Tab/Shift-Tab and
 * Enter/Space; `aria-pressed` says which side is chosen, the labelled group says what is being chosen.
 */
export function PickBanSideChoice({
  labelledBy,
  labels,
  value,
  onChange,
  disabled = false,
  size = "sm"
}: Readonly<{
  /** Id of the visible text naming the choice. */
  labelledBy: string;
  /** Side labels in `state.sides` order. */
  labels: string[];
  value: number | null;
  onChange: (index: number) => void;
  disabled?: boolean;
  size?: "sm" | "lg";
}>) {
  return (
    <div role="group" aria-labelledby={labelledBy} className="flex flex-wrap gap-2">
      {labels.map((label, index) => (
        <Button
          key={index}
          type="button"
          size={size}
          variant={value === index ? "accent" : "outline"}
          className={size === "lg" ? "min-h-11" : undefined}
          aria-pressed={value === index}
          disabled={disabled}
          onClick={() => onChange(index)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

/**
 * Who starts on which side of one game, read off the room's `starting_sides` by the game's position:
 * "{side}: {team}" per seat. Nothing until that game has a side.
 */
export function PickBanSideAssignment({
  startingSides,
  position,
  seats,
  sideLabel
}: Readonly<{
  startingSides: PickBanStartingSides[] | undefined;
  position: number | null;
  seats: PickBanSeat[];
  /** A side code's label in the room's game. */
  sideLabel: (code: string) => string;
}>) {
  const t = useTranslations("pickBan.room");
  const entry = startingSides?.find((sides) => sides.position === position);
  const rows = seats.flatMap((seat) => {
    const code = entry?.sides[String(seat.id)];
    return code == null ? [] : [{ seat, code }];
  });
  if (rows.length === 0) return null;

  return (
    <ul
      data-side-assignment={position ?? undefined}
      className="flex flex-wrap gap-x-4 gap-y-1 text-sm font-medium"
    >
      {rows.map(({ seat, code }) => (
        <li key={seat.id}>{t("sideAssignment", { side: sideLabel(code), team: seat.name })}</li>
      ))}
    </ul>
  );
}
