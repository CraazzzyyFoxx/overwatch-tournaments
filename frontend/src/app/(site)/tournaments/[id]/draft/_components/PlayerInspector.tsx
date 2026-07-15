"use client";

import { Ban, ShieldCheck, X } from "lucide-react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type {
  DraftPickOption,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";

import { optionForSelection, playerRoles } from "../_lib/draft-workspace-model";

interface PlayerInspectorProps {
  player: DraftPlayer | null;
  role: DraftRole | null;
  options: DraftPickOptionsResponse | null;
  safetyRequired: boolean;
  headingId?: string;
  onRoleChange: (role: DraftRole) => void;
  onClose: () => void;
}

export function PlayerInspector({
  player,
  role,
  options,
  safetyRequired,
  headingId = "player-inspector-heading",
  onRoleChange,
  onClose
}: PlayerInspectorProps) {
  const t = useTranslations("draftRedesign");
  if (!player) {
    return (
      <section className="border-t border-[color:var(--aqt-border)] pt-5 text-sm text-[color:var(--aqt-fg-muted)]">
        <p className="font-medium text-[color:var(--aqt-fg)]">{t("inspectorEmptyTitle")}</p>
        <p className="mt-1">{t("inspectorEmptyHint")}</p>
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
  return (
    <section className="border-t border-[color:var(--aqt-border)] pt-5" aria-labelledby={headingId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{t("inspectorCoordinate")}</p>
          <h2 id={headingId} className="mt-1 truncate font-onest text-xl font-semibold">{player.battle_tag ?? `#${player.id}`}</h2>
        </div>
        <Button variant="ghost" size="icon" className="h-11 w-11" onClick={onClose} aria-label={t("closeInspector")}><X className="h-4 w-4" /></Button>
      </div>
      <div className="mt-4 space-y-2">
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("chooseRole")}</p>
        <div className="flex flex-wrap gap-2">
          {roles.map((entry) => {
            const option = optionForSelection(options, player.id, entry);
            const blocked = safetyRequired && option?.is_safe !== true;
            return (
              <button
                key={entry}
                type="button"
                disabled={blocked}
                aria-pressed={role === entry}
                onClick={() => onRoleChange(entry)}
                className={cn(
                  "flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
                  role === entry ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/10" : "border-[color:var(--aqt-border-2)]",
                  blocked && "cursor-not-allowed opacity-45"
                )}
              >
                <PlayerRoleIcon role={getRoleIconName(entry)} size={16} />
                {t(`roles.${entry}`)}
                {blocked ? <Ban className="h-3.5 w-3.5" /> : safetyRequired ? <ShieldCheck className="h-3.5 w-3.5 text-[color:var(--aqt-support)]" /> : null}
              </button>
            );
          })}
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-[color:var(--aqt-border)] pt-4 text-sm">
        <div><dt className="text-xs text-[color:var(--aqt-fg-muted)]">{t("rank")}</dt><dd className="mt-1 font-mono">{role ? player.role_ranks[role] ?? player.rank_value ?? "—" : player.rank_value ?? "—"}</dd></div>
        <div><dt className="text-xs text-[color:var(--aqt-fg-muted)]">{t("selectionSafety")}</dt><dd className="mt-1">{!safetyRequired ? t("waitingForTurn") : selectedOption?.is_safe ? t("safeOption") : t("unsafeOption")}</dd></div>
      </dl>
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
