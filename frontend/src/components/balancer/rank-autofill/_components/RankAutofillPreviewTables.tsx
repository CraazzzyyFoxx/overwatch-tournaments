"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { EYEBROW_CLASS, TONE_CLASS, TONE_TEXT } from "@/components/admin/tone";
import { Checkbox } from "@/components/ui/checkbox";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { ROLE_LABELS, getRoleIconName } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type {
  RegistrationRankAutofillPlayer,
  RegistrationRankAutofillResponse,
  RegistrationRankAutofillRole
} from "@/types/balancer-admin.types";

function formatCapturedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function formatRankSource(role: RegistrationRankAutofillRole): string {
  const nativeRank = role.division
    ? `${role.division}${role.tier != null ? ` ${role.tier}` : ""}`
    : null;
  const capturedAt = role.captured_at ? formatCapturedAt(role.captured_at) : null;
  return [role.platform?.toUpperCase(), nativeRank, capturedAt].filter(Boolean).join(" / ");
}

/**
 * Per-role breakdown of the suggestion: OW (week composite), balancer (division history) and
 * analytics, with the chosen signal marked. Lines with no value are omitted.
 */
function formatBlendBreakdown(role: RegistrationRankAutofillRole): string[] {
  // Plain-text `title` content, so the marker has to stay a word rather than an icon.
  const mark = (source: RegistrationRankAutofillRole["used_source"]) =>
    role.used_source === source ? " (used)" : "";
  const lines: string[] = [];
  if (role.ow_rank_value != null) {
    lines.push(`OW (week) ${role.ow_rank_value}${mark("ow")}`);
  }
  if (role.division_history_rank_value != null) {
    lines.push(`balancer ${role.division_history_rank_value}${mark("division_history")}`);
  }
  if (role.analytics_rank_value != null) {
    lines.push(`analytics ${role.analytics_rank_value}${mark("analytics")}`);
  }
  return lines;
}

/** A role whose current registration rank disagrees with the suggested rank (both present). */
function roleHasMismatch(role: RegistrationRankAutofillRole): boolean {
  return (
    role.current_rank_value != null &&
    role.parsed_rank_value != null &&
    role.current_rank_value !== role.parsed_rank_value
  );
}

type RolePillTone = "update" | "mismatch" | "unverified" | "blocked" | "neutral";

// Role pills are the admin's tone vocabulary, not a private palette: the same
// green/amber/rose here as on every other status surface.
const ROLE_PILL_TONE_CLASS: Record<RolePillTone, string> = {
  update: TONE_CLASS.success,
  mismatch: TONE_CLASS.danger,
  unverified: TONE_CLASS.warning,
  blocked: TONE_CLASS.warning,
  neutral: TONE_CLASS.neutral
};

/**
 * Precedence is deliberate: what will be written outranks a kept rank that
 * merely disagrees with the suggestion, which in turn outranks the reasons
 * nothing was written at all. A mismatched unverified rank reads as a mismatch,
 * because the disagreement is the thing a reviewer has to resolve.
 */
function resolveRolePillTone(role: RegistrationRankAutofillRole): RolePillTone {
  if (role.action === "set" || role.action === "overwrite") return "update";
  if (roleHasMismatch(role)) return "mismatch";
  if (role.action === "unverified") return "unverified";
  if (role.action === "blocked" || role.action === "missing_rank") return "blocked";
  return "neutral";
}

function playerHasMismatch(player: RegistrationRankAutofillPlayer): boolean {
  return player.roles.some(roleHasMismatch);
}

function hasUnverifiedRole(player: RegistrationRankAutofillPlayer): boolean {
  return player.roles.some((role) => role.action === "unverified");
}

function playerLabel(player: RegistrationRankAutofillPlayer): string {
  return player.battle_tag ?? player.display_name ?? `#${player.registration_id}`;
}

function RankAutofillRolePill({ role }: Readonly<{ role: RegistrationRankAutofillRole }>) {
  const t = useTranslations();
  const grid = useDivisionGrid();
  const roleLabel = ROLE_LABELS[role.role] ?? role.role;
  const source = formatRankSource(role);
  const breakdown = formatBlendBreakdown(role);
  const tone = resolveRolePillTone(role);
  // The tone already ranks these two apart: an update is what gets written, a
  // mismatch is a kept rank that disagrees with the suggestion (overwrite off)
  // — surfaced, not applied. The layout below branches on that distinction.
  const isUpdate = tone === "update";
  const isMismatch = tone === "mismatch";
  // Read straight off the action: an unverified rank that also disagrees shows
  // the mismatch tone, yet still has to say it was never verified.
  const isUnverified = role.action === "unverified";
  const isMissing = role.action === "missing_rank";

  const parsedDivision =
    role.parsed_rank_value != null ? resolveDivisionFromRank(grid, role.parsed_rank_value) : null;
  const currentDivision =
    role.current_rank_value != null ? resolveDivisionFromRank(grid, role.current_rank_value) : null;

  const showsTransition = (isUpdate || isMismatch) && role.current_rank_value != null;
  const primaryRank =
    isUpdate || isMismatch
      ? role.parsed_rank_value
      : (role.current_rank_value ?? role.parsed_rank_value);
  const primaryDivision =
    isUpdate || isMismatch ? parsedDivision : (currentDivision ?? parsedDivision);

  return (
    <div
      className={cn(
        "inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
        ROLE_PILL_TONE_CLASS[tone]
      )}
      title={[[role.reason, source].filter(Boolean).join(" / "), ...breakdown]
        .filter(Boolean)
        .join("\n")}
    >
      <span className="shrink-0">
        <PlayerRoleIcon
          role={getRoleIconName(role.role)}
          size={14}
          color="currentColor"
          decorative
        />
      </span>
      <span className="sr-only">{roleLabel}</span>

      {isMissing ? (
        <span className="opacity-60">{t("rankAutofill.pillMissing")}</span>
      ) : (
        <>
          {showsTransition && (
            <>
              {currentDivision != null && (
                <DivisionIcon division={currentDivision} width={16} height={16} />
              )}
              <span className="tabular-nums opacity-50">{role.current_rank_value}</span>
              <ArrowRight className="size-4 shrink-0 opacity-40" aria-hidden />
            </>
          )}
          {primaryDivision != null && (
            <DivisionIcon division={primaryDivision} width={16} height={16} />
          )}
          <span className="tabular-nums">{primaryRank ?? "-"}</span>
          {isUnverified && <span className="opacity-60">{t("rankAutofill.pillUnverified")}</span>}
        </>
      )}
    </div>
  );
}

interface RankAutofillPreviewTablesProps {
  preview: RegistrationRankAutofillResponse | undefined;
  loading: boolean;
  search: string;
  mismatchOnly: boolean;
  selectedIds: Set<number>;
  onToggle: (registrationId: number, checked: boolean) => void;
  onToggleAll: (checked: boolean, ids: number[]) => void;
}

export function RankAutofillPreviewTables({
  preview,
  loading,
  search,
  mismatchOnly,
  selectedIds,
  onToggle,
  onToggleAll
}: Readonly<RankAutofillPreviewTablesProps>) {
  const t = useTranslations();

  if (!preview && !loading) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-[color:var(--aqt-fg-dim)]">
        {t("rankAutofill.previewNotLoaded")}
      </div>
    );
  }
  if (!preview) {
    return null;
  }

  const query = search.trim().toLowerCase();
  const matchesSearch = (player: RegistrationRankAutofillPlayer) =>
    query === "" ||
    (player.battle_tag ?? "").toLowerCase().includes(query) ||
    (player.display_name ?? "").toLowerCase().includes(query) ||
    String(player.registration_id).includes(query);

  const visiblePlayers = preview.players.filter(
    (player) => matchesSearch(player) && (!mismatchOnly || playerHasMismatch(player))
  );

  if (visiblePlayers.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-[color:var(--aqt-fg-dim)]">
        {t("rankAutofill.noMatches")}
      </div>
    );
  }

  const updatablePlayers = visiblePlayers.filter(
    (player) => player.status === "will_update" || player.status === "applied"
  );
  const skippedPlayers = visiblePlayers.filter((player) => player.status === "skipped");
  const unchangedPlayers = visiblePlayers.filter((player) => player.status === "unchanged");

  const selectableIds = updatablePlayers.map((player) => player.registration_id);
  const allChecked = selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));

  return (
    <div className="grid grid-cols-1 gap-4 md:h-full md:min-h-0 md:grid-cols-3 md:grid-rows-1">
      {/* Column 1 — To assign (with per-player selection) */}
      <section className="flex min-w-0 flex-col md:min-h-0">
        <div className="mb-2 flex shrink-0 items-center gap-2">
          <Checkbox
            checked={allChecked}
            onCheckedChange={(checked) => onToggleAll(checked === true, selectableIds)}
            disabled={selectableIds.length === 0 || loading}
            aria-label={t("rankAutofill.selectAllAria")}
          />
          <span className={EYEBROW_CLASS}>{t("rankAutofill.sections.assign")}</span>
          <StatusPill tone="success" className="tabular-nums">
            {selectedIds.size}/{updatablePlayers.length}
          </StatusPill>
        </div>
        {updatablePlayers.length === 0 ? (
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">
            {t("rankAutofill.noRanksToUpdate")}
          </p>
        ) : (
          <div className="flex flex-col gap-2 md:min-h-0 md:flex-1 md:overflow-y-auto md:pr-1">
            {updatablePlayers.map((player) => (
              <label
                key={player.registration_id}
                className="flex min-w-0 cursor-pointer flex-col gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] p-2.5 hover:bg-[color:var(--aqt-overlay-3)]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Checkbox
                    className="shrink-0"
                    checked={selectedIds.has(player.registration_id)}
                    onCheckedChange={(checked) =>
                      onToggle(player.registration_id, checked === true)
                    }
                    disabled={loading}
                    aria-label={t("rankAutofill.selectAria", { name: playerLabel(player) })}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-[color:var(--aqt-fg)]">
                    {playerLabel(player)}
                  </span>
                  {player.partial && (
                    <StatusPill tone="warning">{t("rankAutofill.badgePartial")}</StatusPill>
                  )}
                  {player.will_add_to_balancer && (
                    <StatusPill tone="info">
                      <ArrowRight className="size-3 shrink-0" aria-hidden />
                      Balancer
                    </StatusPill>
                  )}
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-1.5 pl-6">
                  <span className="text-xs text-[color:var(--aqt-fg-dim)]">
                    #{player.registration_id}
                  </span>
                  {player.roles
                    .filter((role) => role.action === "set" || role.action === "overwrite")
                    .map((role) => (
                      <RankAutofillRolePill key={role.role} role={role} />
                    ))}
                </div>
              </label>
            ))}
          </div>
        )}
      </section>

      {/* Column 2 — Skipped */}
      <section className="flex min-w-0 flex-col md:min-h-0">
        <div className="mb-2 flex shrink-0 items-center gap-2">
          <span className={EYEBROW_CLASS}>{t("rankAutofill.sections.skipped")}</span>
          {skippedPlayers.length > 0 && (
            <StatusPill tone="warning" className="tabular-nums">
              {skippedPlayers.length}
            </StatusPill>
          )}
        </div>
        {skippedPlayers.length === 0 ? (
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("rankAutofill.noneSkipped")}</p>
        ) : (
          <div className="flex flex-col gap-2 md:min-h-0 md:flex-1 md:overflow-y-auto md:pr-1">
            {skippedPlayers.map((player) => (
              <div
                key={player.registration_id}
                className="min-w-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] p-2.5"
              >
                <div className="truncate text-xs font-medium text-[color:var(--aqt-fg-muted)]">
                  {playerLabel(player)}
                </div>
                <div className={cn("mt-0.5 text-xs leading-4", TONE_TEXT.warning)}>
                  {player.reason ?? t("rankAutofill.skippedFallback")}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {player.roles.map((role) => (
                    <RankAutofillRolePill key={role.role} role={role} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Column 3 — Already set */}
      <section className="flex min-w-0 flex-col md:min-h-0">
        <div className="mb-2 flex shrink-0 items-center gap-2">
          <span className={EYEBROW_CLASS}>{t("rankAutofill.sections.alreadySet")}</span>
          {unchangedPlayers.length > 0 && (
            <StatusPill tone="neutral" className="tabular-nums">
              {unchangedPlayers.length}
            </StatusPill>
          )}
        </div>
        {unchangedPlayers.length === 0 ? (
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("rankAutofill.noUnchanged")}</p>
        ) : (
          <div className="flex flex-col gap-2 md:min-h-0 md:flex-1 md:overflow-y-auto md:pr-1">
            {unchangedPlayers.map((player) => {
              const auditRoles = player.roles.filter(
                (role) => role.action === "unverified" || roleHasMismatch(role)
              );
              return (
                <div
                  key={player.registration_id}
                  className="min-w-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] p-2.5"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-[color:var(--aqt-fg-muted)]">
                      {playerLabel(player)}
                    </span>
                    {hasUnverifiedRole(player) && (
                      <StatusPill tone="warning">{t("rankAutofill.badgeUnverified")}</StatusPill>
                    )}
                    {playerHasMismatch(player) && (
                      <StatusPill tone="danger">{t("rankAutofill.badgeMismatch")}</StatusPill>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs leading-4 text-[color:var(--aqt-fg-dim)]">
                    {player.reason ?? t("rankAutofill.unchangedFallback")}
                  </div>
                  {auditRoles.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {auditRoles.map((role) => (
                        <RankAutofillRolePill key={role.role} role={role} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
