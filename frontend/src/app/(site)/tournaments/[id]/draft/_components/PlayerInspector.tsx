"use client";

import { Ban, Crown, HelpCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type {
  DraftPickOption,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getPlayerSlug } from "@/utils/player";

import { optionForSelection, playerRoles } from "../_lib/draft-workspace-model";

const BADGE_CLASS =
  "rounded border border-[color:var(--aqt-border-2)] px-1 text-[10px] uppercase tracking-wide text-[color:var(--aqt-fg-muted)]";

interface PlayerInspectorProps {
  player: DraftPlayer | null;
  role: DraftRole | null;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  headingId?: string;
  onRoleChange: (role: DraftRole) => void;
  onClose: () => void;
  divisionGrid: DivisionGrid;
}

export function PlayerInspector({
  player,
  role,
  options,
  safetyRequired,
  headingId = "player-inspector-heading",
  onRoleChange,
  onClose,
  divisionGrid
}: PlayerInspectorProps) {
  const t = useTranslations("draftRedesign");
  if (!player) {
    return (
      <section className="rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] p-5 text-sm text-[color:var(--aqt-fg-muted)]">
        <p className="flex items-center gap-1.5 font-medium text-[color:var(--aqt-fg)]">
          {t("inspectorEmptyTitle")}
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="grid h-4 w-4 place-items-center rounded-full text-[color:var(--aqt-fg-faint)] outline-none transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  aria-label={t("howItWorks")}
                >
                  <HelpCircle className="h-3.5 w-3.5" aria-hidden />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[16rem] text-xs">{t("inspectorEmptyHint")}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </p>
      </section>
    );
  }
  const roles = playerRoles(player);
  const selectedOption = role ? optionForSelection(options, player.id, role) : null;
  const blockedOptions = safetyRequired
    ? roles
        .map((entry) => optionForSelection(options, player.id, entry))
        .filter((option): option is DraftPickOption => option != null && !option.is_safe)
    : [];
  const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
  const headerDivision = player.division_number ?? resolveDivisionFromRank(divisionGrid, player.rank_value);
  const notes =
    typeof player.additional_info.notes === "string" && player.additional_info.notes.trim() !== ""
      ? player.additional_info.notes
      : null;
  return (
    <section className="rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] p-4" aria-labelledby={headingId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{t("inspectorCoordinate")}</p>
          <h2 id={headingId} className="mt-1 flex items-center gap-2 font-onest text-lg font-semibold">
            {profileSlug ? (
              <Link href={`/users/${profileSlug}`} className="truncate hover:text-[color:var(--aqt-teal)] hover:underline">
                {player.battle_tag}
              </Link>
            ) : (
              <span className="truncate">{`#${player.id}`}</span>
            )}
            {player.is_captain && <Crown className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-label={t("captain")} />}
          </h2>
          <p className="font-mono text-xs text-[color:var(--aqt-fg-faint)]">{`#${player.id}`}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {headerDivision != null && (
            <span className="flex flex-col items-center gap-0.5" title={getDivisionLabel(divisionGrid, headerDivision) ?? undefined}>
              <PlayerDivisionIcon division={headerDivision} tournamentGrid={divisionGrid} width={32} height={32} className="h-8 w-8 object-contain" />
              <span className="text-[10px] text-[color:var(--aqt-fg-muted)]">{getDivisionLabel(divisionGrid, headerDivision)}</span>
            </span>
          )}
          <Button variant="ghost" size="icon" className="h-11 w-11" onClick={onClose} aria-label={t("closeInspector")}><X className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 empty:hidden">
        {player.sub_role && <span className={BADGE_CLASS}>{formatSubRoleLabel(player.sub_role)}</span>}
        {player.is_flex && <span className={BADGE_CLASS}>{t("flex")}</span>}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs text-[color:var(--aqt-fg-muted)]">{t("chooseRole")}</p>
        <div className="flex gap-2">
          {roles.map((entry, index) => {
            const option = optionForSelection(options, player.id, entry);
            const blocked = safetyRequired && option?.is_safe !== true;
            const roleRank = player.role_ranks[entry] ?? player.rank_value ?? null;
            const roleDivision = resolveDivisionFromRank(divisionGrid, roleRank);
            const active = role === entry;
            return (
              <button
                key={entry}
                type="button"
                disabled={blocked}
                aria-pressed={active}
                title={roleRank != null ? `${roleRank} SR` : undefined}
                onClick={() => onRoleChange(entry)}
                className={cn(
                  "relative flex min-w-0 flex-1 flex-col items-center gap-1.5 rounded-lg border px-2 py-2.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                  active
                    ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/10"
                    : "border-[color:var(--aqt-border-2)] hover:border-[color:var(--aqt-teal)]/50",
                  blocked && "cursor-not-allowed opacity-45"
                )}
              >
                <span
                  className="absolute right-1.5 top-1.5 font-mono text-[10px] font-semibold text-[color:var(--aqt-fg-faint)]"
                  aria-label={t("rolePriority", { n: index + 1 })}
                >
                  {index + 1}
                </span>
                <PlayerRoleIcon role={getRoleIconName(entry)} size={20} color={ROLE_ACCENT[entry]} />
                <span className="max-w-full truncate text-[11px] font-medium uppercase tracking-wide">{t(`roles.${entry}`)}</span>
                {blocked ? (
                  <Ban className="h-[30px] w-[30px] text-[color:var(--aqt-live)]" aria-label={t("unsafeOption")} />
                ) : roleDivision != null ? (
                  <PlayerDivisionIcon division={roleDivision} tournamentGrid={divisionGrid} width={30} height={30} className="h-[30px] w-[30px] object-contain" />
                ) : (
                  <span className="flex h-[30px] items-center text-sm text-[color:var(--aqt-fg-faint)]">—</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {notes && (
        <div className="mt-3 border-t border-[color:var(--aqt-border)] pt-3 text-sm">
          <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("note")}</p>
          <p className="mt-1 text-[color:var(--aqt-fg)]">{notes}</p>
        </div>
      )}

      {safetyRequired && selectedOption && !selectedOption.is_safe && (
        <div className="mt-4 border-l-2 border-[color:var(--aqt-live)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t(`optionReason.${selectedOption.reason_code === "role_filled" ? "role_filled" : "role_shortage"}`)}
        </div>
      )}
      {blockedOptions.length > 1 && (
        <ul className="mt-4 space-y-2 text-xs text-[color:var(--aqt-fg-muted)]">
          {blockedOptions
            .filter((option) => option.role !== selectedOption?.role)
            .map((option) => (
              <li key={option.role} className="flex gap-2">
                <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-live)]" />
                <span>
                  <strong className="text-[color:var(--aqt-fg)]">{t(`roles.${option.role}`)}:</strong>{" "}
                  {t(`optionReason.${option.reason_code === "role_filled" ? "role_filled" : "role_shortage"}`)}
                </span>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}
