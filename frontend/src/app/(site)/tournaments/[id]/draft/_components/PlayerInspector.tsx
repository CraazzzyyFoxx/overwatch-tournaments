"use client";

import { Ban, Crown, HelpCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { HeroCoord } from "@/components/site/PageHero";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
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
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

import { optionForSelection, playerRoles, roleTopHeroes } from "../_lib/draft-workspace-model";

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
          <HeroCoord>{t("inspectorCoordinate")}</HeroCoord>
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
            <span title={getDivisionLabel(divisionGrid, headerDivision) ?? undefined}>
              <PlayerDivisionIcon division={headerDivision} tournamentGrid={divisionGrid} width={32} height={32} className="h-8 w-8 object-contain" />
            </span>
          )}
          <Button variant="ghost" size="icon" className="h-9 w-9" onClick={onClose} aria-label={t("closeInspector")}><X className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 empty:hidden">
        {player.sub_role && <span className={BADGE_CLASS}>{formatSubRoleLabel(player.sub_role)}</span>}
        {player.is_flex && <span className={BADGE_CLASS}>{t("flex")}</span>}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs text-[color:var(--aqt-fg-muted)]">{t("chooseRole")}</p>
        <div className="flex flex-col gap-2 sm:flex-row">
          {roles.map((entry) => {
            const option = optionForSelection(options, player.id, entry);
            const blocked = safetyRequired && option?.is_safe !== true;
            const roleRank = player.role_ranks[entry] ?? player.rank_value ?? null;
            const roleDivision = resolveDivisionFromRank(divisionGrid, roleRank);
            const heroes = roleTopHeroes(player, entry);
            const active = role === entry;
            const isPrimary = entry === player.primary_role;
            return (
              <button
                key={entry}
                type="button"
                disabled={blocked}
                aria-pressed={active}
                title={[isPrimary ? t("primaryRole") : null, roleRank != null ? `${roleRank} SR` : null].filter(Boolean).join(" · ") || undefined}
                onClick={() => onRoleChange(entry)}
                className={cn(
                  "flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border px-3 py-1.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                  isPrimary ? "border-[color:var(--aqt-teal)]/60" : "border-[color:var(--aqt-border-2)]",
                  active ? "bg-[color:var(--aqt-teal)]/15" : "hover:border-[color:var(--aqt-teal)]/50",
                  blocked && "cursor-not-allowed opacity-45"
                )}
              >
                <PlayerRoleIcon role={getRoleIconName(entry)} size={18} color={ROLE_ACCENT[entry]} />
                <span className={cn("min-w-0 truncate text-[11px] font-medium uppercase tracking-wide", active && "text-[color:var(--aqt-teal)]")}>
                  {t(`roles.${entry}`)}
                </span>
                <span className="ml-auto flex shrink-0 items-center gap-1.5">
                  {heroes.length > 0 && (
                    <AvatarStack size={24} max={3}>
                      {heroes.map((hero) => (
                        <Avatar key={hero.slug} className="h-6 w-6" title={hero.slug}>
                          <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                        </Avatar>
                      ))}
                    </AvatarStack>
                  )}
                  {blocked ? (
                    <Ban className="h-4 w-4 text-[color:var(--aqt-live)]" aria-label={t("unsafeOption")} />
                  ) : roleDivision != null ? (
                    <PlayerDivisionIcon division={roleDivision} tournamentGrid={divisionGrid} width={24} height={24} className="h-6 w-6 object-contain" />
                  ) : (
                    <span className="text-sm text-[color:var(--aqt-fg-faint)]">—</span>
                  )}
                </span>
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
