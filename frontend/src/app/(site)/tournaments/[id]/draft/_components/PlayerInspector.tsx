"use client";

import { Ban, Crown, ShieldCheck, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
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
        <p className="font-medium text-[color:var(--aqt-fg)]">{t("inspectorEmptyTitle")}</p>
        <p className="mt-1">{t("inspectorEmptyHint")}</p>
      </section>
    );
  }
  const roles = playerRoles(player);
  const secondaryRoles = roles.filter((entry) => entry !== player.primary_role);
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
    <section className="rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] p-5" aria-labelledby={headingId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{t("inspectorCoordinate")}</p>
          <h2 id={headingId} className="mt-1 flex items-center gap-2 font-onest text-xl font-semibold">
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

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {player.sub_role && <span className={BADGE_CLASS}>{formatSubRoleLabel(player.sub_role)}</span>}
        {player.is_flex && <span className={BADGE_CLASS}>{t("flex")}</span>}
        {secondaryRoles.length > 0 && (
          <span className="flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
            {t("secondaryRoles")}:
            {secondaryRoles.map((entry) => (
              <span key={entry} className={BADGE_CLASS}>{t(`roles.${entry}`)}</span>
            ))}
          </span>
        )}
      </div>

      <div className="mt-4 space-y-2">
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("chooseRole")}</p>
        <div className="space-y-2">
          {roles.map((entry) => {
            const option = optionForSelection(options, player.id, entry);
            const blocked = safetyRequired && option?.is_safe !== true;
            const roleRank = player.role_ranks[entry] ?? player.rank_value ?? null;
            const roleDivision = resolveDivisionFromRank(divisionGrid, roleRank);
            const heroes = roleTopHeroes(player, entry);
            return (
              <button
                key={entry}
                type="button"
                disabled={blocked}
                aria-pressed={role === entry}
                onClick={() => onRoleChange(entry)}
                className={cn(
                  "flex min-h-11 w-full flex-col gap-1.5 rounded-lg border px-3 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                  role === entry ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/10" : "border-[color:var(--aqt-border-2)]",
                  blocked && "cursor-not-allowed opacity-45"
                )}
              >
                <span className="flex items-center gap-2">
                  <PlayerRoleIcon role={getRoleIconName(entry)} size={16} color={ROLE_ACCENT[entry]} />
                  <span className="flex-1 truncate">{t(`roles.${entry}`)}</span>
                  {blocked ? <Ban className="h-3.5 w-3.5 shrink-0" aria-label={t("unsafeOption")} /> : safetyRequired ? <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-support)]" aria-label={t("safeOption")} /> : null}
                </span>
                <span className="flex items-center gap-2 pl-6">
                  <span className="flex items-center gap-1 font-mono text-xs text-[color:var(--aqt-fg-muted)]">
                    {roleRank != null ? `${roleRank} SR` : "—"}
                    {roleDivision != null && (
                      <PlayerDivisionIcon division={roleDivision} tournamentGrid={divisionGrid} width={18} height={18} className="h-[18px] w-[18px] object-contain" />
                    )}
                  </span>
                  {heroes.length > 0 && (
                    <AvatarStack size={24} max={3} className="ml-auto">
                      {heroes.map((hero) => (
                        <Avatar key={hero.slug} className="h-6 w-6" title={hero.slug}>
                          <AvatarImage src={getHeroIconUrl(hero.slug, hero.imagePath)} alt={hero.slug} />
                        </Avatar>
                      ))}
                    </AvatarStack>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {notes && (
        <div className="mt-4 border-t border-[color:var(--aqt-border)] pt-4 text-sm">
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
