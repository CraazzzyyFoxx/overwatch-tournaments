"use client";

import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import { isRosterSlotCode } from "@/lib/roster/shape";

/**
 * A roster slot rendered as its role glyph, on the rows that display a slot
 * rather than ask you to pick one.
 *
 * The `isRosterSlotCode` gate is the whole point. `normalizePlayerRole` falls
 * back to `Damage` for anything it does not recognise (see its docstring), so
 * handing it a slot code from a newer server would render a confident, wrong
 * Damage icon. An unknown code renders as itself instead — the same rule
 * `isRosterSlotCode` already states for the typed slot translations.
 *
 * The accessible name comes from `rosterShape.slotCodes`, not
 * `PlayerRoleIcon`'s own `common.roles.*` default: this feature deliberately
 * speaks one slot vocabulary everywhere, so a roster never announces "DPS"
 * next to a shortfall that reads "Урон".
 *
 * `decorative` is for rows whose own text already names the slot; the default
 * assumes the glyph is the only thing naming it, and announces the role.
 */
export default function RosterSlotGlyph({
  code,
  size = 16,
  decorative = false
}: Readonly<{
  code: string | null | undefined;
  size?: number;
  decorative?: boolean;
}>) {
  const tSlot = useTranslations("rosterShape.slotCodes");

  if (!code) return null;
  if (!isRosterSlotCode(code)) {
    // Decorative means the row's own text already names the slot — including
    // the unknown-code fallback that text goes through — so repeating the raw
    // code here would just print it twice.
    if (decorative) return null;
    return <span className="text-xs text-[color:var(--aqt-fg-muted)]">{code}</span>;
  }

  return (
    <PlayerRoleIcon
      role={normalizePlayerRole(code)}
      size={size}
      label={tSlot(code)}
      decorative={decorative}
    />
  );
}
