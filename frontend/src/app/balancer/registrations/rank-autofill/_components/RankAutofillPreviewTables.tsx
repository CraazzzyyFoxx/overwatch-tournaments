"use client";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Checkbox } from "@/components/ui/checkbox";
import { useTranslation } from "@/i18n/LanguageContext";
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
  const mark = (source: RegistrationRankAutofillRole["used_source"]) =>
    role.used_source === source ? " ← used" : "";
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

export function RankAutofillRolePill({ role }: { role: RegistrationRankAutofillRole }) {
  const { t } = useTranslation();
  const grid = useDivisionGrid();
  const roleLabel = ROLE_LABELS[role.role] ?? role.role;
  const source = formatRankSource(role);
  const breakdown = formatBlendBreakdown(role);
  const isUpdate = role.action === "set" || role.action === "overwrite";
  const isUnverified = role.action === "unverified";
  const isBlocked = role.action === "blocked" || role.action === "missing_rank";
  const isMissing = role.action === "missing_rank";

  const parsedDivision =
    role.parsed_rank_value != null ? resolveDivisionFromRank(grid, role.parsed_rank_value) : null;
  const currentDivision =
    role.current_rank_value != null ? resolveDivisionFromRank(grid, role.current_rank_value) : null;

  const primaryRank = isUpdate
    ? role.parsed_rank_value
    : (role.current_rank_value ?? role.parsed_rank_value);
  const primaryDivision = isUpdate ? parsedDivision : (currentDivision ?? parsedDivision);

  return (
    <div
      className={cn(
        "inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[11px]",
        isUpdate
          ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"
          : isUnverified
            ? "border-amber-400/25 bg-amber-500/10 text-amber-100"
            : isBlocked
              ? "border-orange-400/25 bg-orange-500/10 text-orange-100"
              : "border-white/10 bg-white/5 text-white/60"
      )}
      title={[[role.reason, source].filter(Boolean).join(" / "), ...breakdown]
        .filter(Boolean)
        .join("\n")}
    >
      <span className="shrink-0" aria-hidden="true">
        <PlayerRoleIcon role={getRoleIconName(role.role)} size={14} color="currentColor" />
      </span>
      <span className="sr-only">{roleLabel}</span>

      {isMissing ? (
        <span className="opacity-60">{t("rankAutofill.pillMissing")}</span>
      ) : (
        <>
          {isUpdate && role.current_rank_value != null && (
            <>
              {currentDivision != null && (
                <PlayerDivisionIcon division={currentDivision} width={16} height={16} />
              )}
              <span className="tabular-nums opacity-50">{role.current_rank_value}</span>
              <span className="opacity-40">→</span>
            </>
          )}
          {primaryDivision != null && (
            <PlayerDivisionIcon division={primaryDivision} width={16} height={16} />
          )}
          <span className="tabular-nums">{primaryRank ?? "-"}</span>
          {isUnverified && <span className="opacity-60">{t("rankAutofill.pillUnverified")}</span>}
        </>
      )}
    </div>
  );
}

function playerLabel(player: RegistrationRankAutofillPlayer): string {
  return player.battle_tag ?? player.display_name ?? `#${player.registration_id}`;
}

function hasUnverifiedRole(player: RegistrationRankAutofillPlayer): boolean {
  return player.roles.some((role) => role.action === "unverified");
}

interface RankAutofillPreviewTablesProps {
  preview: RegistrationRankAutofillResponse | undefined;
  loading: boolean;
  selectedIds: Set<number>;
  onToggle: (registrationId: number, checked: boolean) => void;
  onToggleAll: (checked: boolean) => void;
}

export function RankAutofillPreviewTables({
  preview,
  loading,
  selectedIds,
  onToggle,
  onToggleAll
}: RankAutofillPreviewTablesProps) {
  const { t } = useTranslation();

  if (!preview && !loading) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-white/30">
        {t("rankAutofill.previewNotLoaded")}
      </div>
    );
  }
  if (!preview) {
    return null;
  }

  const updatablePlayers = preview.players.filter(
    (player) => player.status === "will_update" || player.status === "applied"
  );
  const skippedPlayers = preview.players.filter((player) => player.status === "skipped");
  const unchangedPlayers = preview.players.filter((player) => player.status === "unchanged");

  const selectableIds = updatablePlayers.map((player) => player.registration_id);
  const allChecked =
    selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));

  return (
    <div className="divide-y divide-white/[0.06]">
      {/* To assign — with per-player selection */}
      <div className="px-1 py-3">
        <div className="mb-2 flex items-center gap-2">
          <Checkbox
            checked={allChecked}
            onCheckedChange={(checked) => onToggleAll(checked === true)}
            disabled={selectableIds.length === 0 || loading}
            aria-label={t("rankAutofill.selectAllAria")}
          />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
            {t("rankAutofill.sections.assign")}
          </span>
          <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
            {selectedIds.size}/{updatablePlayers.length}
          </span>
        </div>
        {updatablePlayers.length === 0 ? (
          <p className="text-xs text-white/30">{t("rankAutofill.noRanksToUpdate")}</p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {updatablePlayers.map((player) => (
              <label
                key={player.registration_id}
                className="flex min-w-0 cursor-pointer flex-col gap-1.5 rounded-lg border border-white/10 bg-white/[0.02] p-2.5 hover:bg-white/[0.04]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Checkbox
                    className="shrink-0"
                    checked={selectedIds.has(player.registration_id)}
                    onCheckedChange={(checked) => onToggle(player.registration_id, checked === true)}
                    disabled={loading}
                    aria-label={t("rankAutofill.selectAria", { name: playerLabel(player) })}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-white/85">
                    {playerLabel(player)}
                  </span>
                  {player.partial && (
                    <span className="shrink-0 rounded border border-amber-400/20 bg-amber-500/10 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-amber-200">
                      {t("rankAutofill.badgePartial")}
                    </span>
                  )}
                  {player.will_add_to_balancer && (
                    <span className="shrink-0 rounded border border-cyan-400/20 bg-cyan-500/10 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-cyan-200">
                      → Balancer
                    </span>
                  )}
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-1.5 pl-6">
                  <span className="text-[11px] text-white/30">#{player.registration_id}</span>
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
      </div>

      {/* Skipped + Already set */}
      <div className="grid gap-px lg:grid-cols-2">
        <div className="px-1 py-3 lg:pr-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              {t("rankAutofill.sections.skipped")}
            </span>
            {skippedPlayers.length > 0 && (
              <span className="rounded-full bg-orange-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-orange-300">
                {skippedPlayers.length}
              </span>
            )}
          </div>
          {skippedPlayers.length === 0 ? (
            <p className="text-xs text-white/30">{t("rankAutofill.noneSkipped")}</p>
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-xl border border-white/10">
              {skippedPlayers.map((player) => (
                <div
                  key={player.registration_id}
                  className="border-b border-white/[0.06] px-3 py-2 last:border-b-0"
                >
                  <div className="truncate text-xs font-medium text-white/75">{playerLabel(player)}</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-orange-200/70">
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
        </div>

        <div className="px-1 py-3 lg:border-l lg:border-white/[0.06] lg:pl-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              {t("rankAutofill.sections.alreadySet")}
            </span>
            {unchangedPlayers.length > 0 && (
              <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold text-white/40">
                {unchangedPlayers.length}
              </span>
            )}
          </div>
          {unchangedPlayers.length === 0 ? (
            <p className="text-xs text-white/30">{t("rankAutofill.noUnchanged")}</p>
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-xl border border-white/10">
              {unchangedPlayers.map((player) => (
                <div
                  key={player.registration_id}
                  className="border-b border-white/[0.06] px-3 py-2 last:border-b-0"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-medium text-white/75">
                      {playerLabel(player)}
                    </span>
                    {hasUnverifiedRole(player) && (
                      <span className="rounded border border-amber-400/20 bg-amber-500/10 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-amber-200">
                        {t("rankAutofill.badgeUnverified")}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-4 text-white/35">
                    {player.reason ?? t("rankAutofill.unchangedFallback")}
                  </div>
                  {hasUnverifiedRole(player) && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {player.roles
                        .filter((role) => role.action === "unverified")
                        .map((role) => (
                          <RankAutofillRolePill key={role.role} role={role} />
                        ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
