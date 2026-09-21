"use client";

import { Ban, Crown, HelpCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { AnswerValue } from "@/components/forms/AnswerValue";
import { HeroCoord } from "@/components/site/PageHero";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { FieldKind } from "@/types/forms.types";
import type {
  DraftPickOption,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

import { optionForSelection, playerRoles, roleTopHeroes } from "@/lib/draft-workspace-model";

const BADGE_CLASS =
  "rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]";

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
}: Readonly<PlayerInspectorProps>) {
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
                  className="relative grid h-4 w-4 place-items-center rounded-full text-[color:var(--aqt-fg-faint)] outline-none transition-colors after:absolute after:-inset-2.5 after:content-[''] hover:text-[color:var(--aqt-teal)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  aria-label={t("inspectorHelp")}
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
  // Every blocked role not already explained above the list, so a single blocked
  // role still gets an inline reason instead of only a title attribute.
  const otherBlockedOptions = blockedOptions.filter(
    (option) => option.role !== selectedOption?.role
  );
  const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
  const headerDivision = resolveDivisionFromRank(divisionGrid, player.effective_rank);
  const notes = player.notes?.trim() ? player.notes : null;
  // Server-side projection: only fields the organizer flagged `show_in_draft`
  // arrive here, already carrying their current label and type.
  const customFields = player.custom_fields ?? [];
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
            {player.is_captain && <Crown className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" role="img" aria-label={t("captain")} />}
          </h2>
          <p className="text-xs text-[color:var(--aqt-fg-faint)]">{`#${player.id}`}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {headerDivision != null && (
            <span title={getDivisionLabel(divisionGrid, headerDivision) ?? undefined}>
              <DivisionIcon division={headerDivision} tournamentGrid={divisionGrid} width={32} height={32} className="h-8 w-8 object-contain" />
            </span>
          )}
          <Button variant="ghost" size="icon" className="h-11 w-11" onClick={onClose} aria-label={t("closeInspector")}><X className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 empty:hidden">
        {player.is_flex && <span className={BADGE_CLASS}>{t("flex")}</span>}
        {player.primary_role == null && <span className={BADGE_CLASS}>{t("noRole")}</span>}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs text-[color:var(--aqt-fg-muted)]">{t("chooseRole")}</p>
        {roles.length === 0 && (
          <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("noRoleHint")}</p>
        )}
        <div className="flex flex-col gap-2 sm:flex-row empty:hidden">
          {roles.map((entry) => {
            const option = optionForSelection(options, player.id, entry);
            const blocked = safetyRequired && option?.is_safe !== true;
            // The role's OWN rank, with no fallback. Lending another role's
            // number to a role the player was never ranked on invents a rating
            // the captain then picks on — three identical division icons for one
            // real number. An unranked role renders the em-dash below; the
            // player's overall strength stays in the header, where
            // `effective_rank` answers it once.
            const roleRank = player.role_ranks[entry] ?? null;
            const roleDivision = resolveDivisionFromRank(divisionGrid, roleRank);
            // Provenance only when it is NOT the registration itself, so the
            // organizer can tell an inherited or Overwatch-derived rank apart
            // from one the player declared.
            const roleSource = player.role_sources[entry] ?? null;
            const borrowedSource =
              roleRank != null && roleSource != null && roleSource !== "registration"
                ? roleSource
                : null;
            const heroes = roleTopHeroes(player, entry);
            const active = role === entry;
            const isPrimary = player.primary_role != null && entry === player.primary_role;
            return (
              <button
                key={entry}
                type="button"
                // aria-disabled, not disabled: an unavailable role must stay
                // focusable so its reason is reachable without a mouse.
                aria-disabled={blocked || undefined}
                aria-pressed={active}
                title={[
                  t(`roles.${entry}`),
                  isPrimary ? t("primaryRole") : null,
                  roleRank != null ? `${roleRank} SR` : null,
                  borrowedSource ? t(`rankSource.${borrowedSource}`) : null
                ].filter(Boolean).join(" · ")}
                onClick={() => {
                  if (!blocked) onRoleChange(entry);
                }}
                className={cn(
                  "flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-lg border px-3 py-1.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                  isPrimary ? "border-[color:var(--aqt-teal)]/60" : "border-[color:var(--aqt-border-2)]",
                  active ? "bg-[color:var(--aqt-teal)]/15" : !blocked && "hover:border-[color:var(--aqt-teal)]/50",
                  blocked && "cursor-not-allowed text-[color:var(--aqt-fg-dim)]"
                )}
              >
                <PlayerRoleIcon role={getRoleIconName(entry)} size={18} color={ROLE_ACCENT[entry]} decorative />
                <span className="sr-only">{t(`roles.${entry}`)}</span>
                {isPrimary && player.sub_role && (
                  <span className="min-w-0 truncate text-label font-medium uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                    {formatSubRoleLabel(player.sub_role)}
                  </span>
                )}
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
                  {borrowedSource && (
                    <span className="text-label uppercase tracking-wide text-[color:var(--aqt-fg-faint)]">
                      {t(`rankSourceShort.${borrowedSource}`)}
                    </span>
                  )}
                  {blocked ? (
                    <Ban className="h-4 w-4 text-[color:var(--aqt-live)]" role="img" aria-label={t("unsafeOption")} />
                  ) : roleDivision != null ? (
                    <DivisionIcon division={roleDivision} tournamentGrid={divisionGrid} width={24} height={24} className="h-6 w-6 object-contain" />
                  ) : (
                    <span className="text-sm text-[color:var(--aqt-fg-faint)]">—</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {(notes || customFields.length > 0) && (
        <div className="mt-3 space-y-3 border-t border-[color:var(--aqt-border)] pt-3 text-sm">
          {notes && (
            <div>
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("note")}</p>
              <p className="mt-1 text-[color:var(--aqt-fg)]">{notes}</p>
            </div>
          )}
          {customFields.length > 0 && (
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              {customFields.map((entry) => (
                <div key={entry.key} className="min-w-0">
                  <dt className="text-xs text-[color:var(--aqt-fg-muted)]">{entry.label}</dt>
                  <dd className="mt-0.5 break-words text-[color:var(--aqt-fg)]">
                    <AnswerValue
                      value={entry.value}
                      kind={entry.type as FieldKind}
                      labels={{ yes: t("customFieldYes"), no: t("customFieldNo") }}
                    />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}

      {safetyRequired && selectedOption && !selectedOption.is_safe && (
        <div className="mt-4 border-l-2 border-[color:var(--aqt-live)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t(`optionReason.${selectedOption.reason_code === "slot_filled" ? "slot_filled" : "role_shortage"}`)}
        </div>
      )}
      {otherBlockedOptions.length > 0 && (
        <ul className="mt-4 space-y-2 text-xs text-[color:var(--aqt-fg-muted)]">
          {otherBlockedOptions.map((option) => (
            <li key={option.role} className="flex gap-2">
              <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color:var(--aqt-live)]" aria-hidden />
              <span>
                <strong className="text-[color:var(--aqt-fg)]">{t(`roles.${option.role}`)}:</strong>{" "}
                {t(`optionReason.${option.reason_code === "slot_filled" ? "slot_filled" : "role_shortage"}`)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
