import { useTranslations } from "next-intl";
import { Check, CornerDownLeft, Plus } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import { PersonLabel } from "@/components/PlayerName";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";

import type { RosterRow } from "../_hooks/useRosterPicker";
import type { MixOwner } from "../pickup-lineup";

/**
 * One roster row: membership indicator on the left, identity in the middle,
 * this host's effective rank per role of the mix's game, read-only, on the right.
 *
 * The whole row is the membership toggle -- there is no picker on it to miss
 * by four pixels anymore, ranks here are read-only. The keyboard path is
 * unchanged: the search field never loses focus, and Enter acts on the
 * cursor row, so adding twelve people is still twelve keystrokes without a
 * single pointer move.
 */
export function RosterRowItem({
  row,
  owner,
  isInMix,
  isCursor,
  canWrite,
  onToggle
}: Readonly<{
  row: RosterRow;
  owner: MixOwner;
  isInMix: boolean;
  isCursor: boolean;
  canWrite: boolean;
  onToggle: () => void;
}>) {
  const t = useTranslations("mixes.addPlayers.row");
  const tLineup = useTranslations("mixes.lineup");
  const slotLabel = useSlotLabel(owner.ontology);
  const label = row.display.name;
  const { grid } = owner;

  return (
    <li data-roster-row>
      <RowButton
        disabled={!canWrite}
        aria-pressed={isInMix}
        aria-label={isInMix ? tLineup("removeNamed", { name: label }) : t("add", { name: label })}
        onClick={onToggle}
        className={cn(
          "relative flex items-center gap-2.5 rounded-lg border px-2 py-1.5",
          // A left rail rather than a filled row: at 24 rows a wash of teal
          // fought the rank crests for attention, and "already in" is a state, not
          // an emphasis.
          isInMix
            ? "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] before:absolute before:inset-y-1.5 before:left-0 before:w-[2px] before:rounded-full before:bg-[color:var(--aqt-teal)]"
            : "border-transparent hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-2)]",
          isCursor && "ring-1 ring-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)]",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-md border transition-colors",
            isInMix
              ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_18%,transparent)] text-[color:var(--aqt-teal)]"
              : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)]"
          )}
        >
          {isInMix ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
        </span>

        <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
          <PersonLabel
            display={row.display}
            className="text-caption font-semibold text-[color:var(--aqt-fg)]"
            tagClassName="text-label"
          />
          {isCursor && canWrite ? (
            <span
              aria-hidden="true"
              className="ml-auto shrink-0 text-[color:color-mix(in_srgb,var(--aqt-teal)_75%,transparent)]"
            >
              <CornerDownLeft className="size-3.5" />
            </span>
          ) : null}
        </span>

        <span className="flex shrink-0 items-center gap-1.5">
          {owner.roles.map((role) => {
            const own = row.authorRanks[role] ?? null;
            const inherited = own == null ? (row.ranks[role] ?? null) : null;
            // The owner game's global ladder: the scale these ranks are on in every
            // workspace, so the crest names the number the balance will use.
            const division = resolveDivisionFromRank(grid, own ?? inherited);
            const rank = own ?? inherited;
            // A one-role game names no role: the crest is just the player's rank.
            const what = owner.showsRoles ? t("roleRank", { role: slotLabel(role) }) : t("rank");
            return (
              <IconTooltip
                key={role}
                label={
                  inherited == null
                    ? t("rankFor", { what, name: label })
                    : t("rankForInherited", { what, name: label, rank: String(inherited) })
                }
                hint={
                  rank == null
                    ? t("noRank")
                    : `${getDivisionLabel(grid, division) ?? ""} \u00B7 ${rank}`
                }
                // Dimmed means "not yours": painting an inherited number the
                // same as the host's own made "set" and "leave alone" look
                // identical, which is the exact mistake layered ranks exist
                // to make visible.
                className={cn(
                  "size-8 items-center justify-center rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]",
                  inherited != null && "opacity-45"
                )}
              >
                {division == null ? (
                  <span aria-hidden="true" className="text-label text-[color:var(--aqt-fg-dim)]">
                    {"\u2014"}
                  </span>
                ) : (
                  <DivisionIcon
                    division={division}
                    tournamentGrid={grid}
                    width={22}
                    height={22}
                  />
                )}
              </IconTooltip>
            );
          })}
        </span>
      </RowButton>
    </li>
  );
}
