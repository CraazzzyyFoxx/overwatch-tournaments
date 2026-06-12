"use client";

import {
  Fragment,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useMemo,
  useState
} from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BadgeInfo,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Globe,
  Loader2,
  Lock,
  MessageSquareText,
  Search,
  RadioTower,
  Pencil,
  ShieldBan,
  ShieldX,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  UserPlus,
  UserRound,
  X,
  XCircle
} from "lucide-react";

import UnifiedRegistrationForm from "@/components/registration/UnifiedRegistrationForm";
import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import BalancerRegistrationsColumnPicker from "@/app/balancer/registrations/_components/BalancerRegistrationsColumnPicker";
import RegistrationRowActions from "@/app/balancer/registrations/_components/RegistrationRowActions";
import BattleTagRankHistory from "@/components/BattleTagRankHistory";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  type BalancerRegistrationColumnDefinition,
  buildBalancerRegistrationColumns
} from "@/app/balancer/registrations/_components/balancerRegistrationColumns";
import {
  type RegistrationGroupingMode,
  groupRegistrations,
  normalizeRegistrationGroupingMode
} from "@/app/balancer/registrations/_components/registrationGrouping";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useColumnVisibility } from "@/hooks/useColumnVisibility";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { mergeStatusOptions } from "@/lib/balancer-statuses";
import { notify } from "@/lib/notify";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { ROLE_LABELS, getRoleIconName, getSubroleLabel } from "@/lib/roles";
import balancerAdminService from "@/services/balancer-admin.service";
import registrationService from "@/services/registration.service";
import type {
  AdminRegistration,
  AdminRegistrationRole,
  BalancerRoleCode,
  BalancerRoleSubtype,
  RegistrationRankAutofillMode,
  RegistrationRankAutofillResponse,
  RegistrationRankAutofillRole
} from "@/types/balancer-admin.types";
import type { RegistrationForm, SubroleCatalog } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";

type RegistrationStatusFilter = string;
type InclusionFilter = "all" | "included" | "excluded";
type SourceFilter = "all" | "manual" | "google_sheets";
type RankAutofillPreviewOptions = {
  overwriteExisting: boolean;
  addToBalancer: boolean;
  mode: RegistrationRankAutofillMode;
};

const RESPONSIVE_CLASS: Record<
  NonNullable<BalancerRegistrationColumnDefinition["responsive"]>,
  string
> = {
  always: "",
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell"
};

const ALIGN_CLASS: Record<NonNullable<BalancerRegistrationColumnDefinition["align"]>, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right"
};

const ROLE_OPTIONS: BalancerRoleCode[] = ["tank", "dps", "support"];

const ADMIN_FORM_STEPS = [{ label: "Accounts" }, { label: "Roles" }, { label: "Details" }];

// Minimal fallback used only until the real registration form (with its
// workspace sub-role catalog) loads. Sub-role options are then data-driven.
const ADMIN_ROLE_FORM: RegistrationForm = {
  id: 0,
  tournament_id: 0,
  workspace_id: 0,
  is_open: true,
  opens_at: null,
  closes_at: null,
  built_in_fields: {
    primary_role: { enabled: true, required: true },
    additional_roles: { enabled: true, required: false }
  },
  custom_fields: []
};

const ADMIN_INPUT_CLASS =
  "h-9 rounded-lg border-white/10 bg-white/[0.03] px-3 text-sm text-white placeholder:text-white/28 focus-visible:ring-0 focus-visible:border-white/20";
const ADMIN_TEXTAREA_CLASS =
  "min-h-[96px] rounded-lg border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/28 focus-visible:ring-0 focus-visible:border-white/20";

const STATUS_CONFIG: Record<string, { icon: typeof Clock; className: string; label: string }> = {
  pending: { icon: Clock, className: "text-amber-500", label: "Pending" },
  approved: { icon: CheckCircle2, className: "text-emerald-500", label: "Approved" },
  rejected: { icon: XCircle, className: "text-red-500", label: "Rejected" },
  withdrawn: { icon: Undo2, className: "text-muted-foreground", label: "Withdrawn" },
  banned: { icon: ShieldBan, className: "text-red-500", label: "Banned" },
  insufficient_data: { icon: AlertTriangle, className: "text-orange-500", label: "Incomplete" }
};

function formatSubmittedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function RolesCell({
  roles,
  catalog
}: {
  roles: AdminRegistration["roles"];
  catalog?: SubroleCatalog;
}) {
  if (roles.length === 0) {
    return <span className="text-muted-foreground">-</span>;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {roles
        .slice()
        .sort((left, right) => left.priority - right.priority)
        .map((role) => {
          const roleLabel = ROLE_LABELS[role.role] ?? role.role;
          const subroleLabel = role.subrole
            ? getSubroleLabel(catalog, role.role, role.subrole)
            : null;
          return (
            <div
              key={`${role.role}-${role.priority}`}
              className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
              title={[
                roleLabel,
                subroleLabel,
                role.rank_value != null ? `${role.rank_value}` : null
              ]
                .filter(Boolean)
                .join(" · ")}
            >
              <span>{roleLabel}</span>
              {subroleLabel ? <span className="text-muted-foreground">{subroleLabel}</span> : null}
              {role.rank_value != null ? (
                <span className="text-muted-foreground">{role.rank_value}</span>
              ) : null}
            </div>
          );
        })}
    </div>
  );
}

function SourceBadge({ source }: { source: AdminRegistration["source"] }) {
  return (
    <Badge variant={source === "google_sheets" ? "secondary" : "outline"}>
      {source === "google_sheets" ? "Google Sheets" : "Manual"}
    </Badge>
  );
}

function BalancerBadge({ registration }: { registration: AdminRegistration }) {
  const status = registration.balancer_status ?? "not_in_balancer";
  const config: Record<string, { variant: "default" | "outline" | "destructive"; label: string }> =
    {
      not_in_balancer: { variant: "outline", label: "Not Added" },
      incomplete: { variant: "destructive", label: "Incomplete" },
      ready: { variant: "default", label: "Ready" }
    };
  const { variant, label } = config[status] ?? config.not_in_balancer;
  return <Badge variant={variant}>{label}</Badge>;
}

function CheckInBadge({ registration }: { registration: AdminRegistration }) {
  return (
    <Badge variant={registration.checked_in ? "default" : "outline"}>
      {registration.checked_in ? "Checked In" : "Not Checked In"}
    </Badge>
  );
}

function formatRankSource(role: RegistrationRankAutofillRole): string {
  const nativeRank = role.division
    ? `${role.division}${role.tier != null ? ` ${role.tier}` : ""}`
    : null;
  const capturedAt = role.captured_at ? formatSubmittedAt(role.captured_at) : null;
  return [role.platform?.toUpperCase(), nativeRank, capturedAt].filter(Boolean).join(" / ");
}

/**
 * Per-role breakdown of the blended suggestion: division history + OW peak (current season) +
 * OW current, with the chosen signal marked. Lines with no value are omitted.
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

function RankAutofillRolePill({ role }: { role: RegistrationRankAutofillRole }) {
  const grid = useDivisionGrid();
  const roleLabel = ROLE_LABELS[role.role] ?? role.role;
  const source = formatRankSource(role);
  const breakdown = formatBlendBreakdown(role);
  const isUpdate = role.action === "set" || role.action === "overwrite";
  const isBlocked = role.action === "blocked" || role.action === "missing_rank";
  const isMissing = role.action === "missing_rank";

  const parsedDivision =
    role.parsed_rank_value != null ? resolveDivisionFromRank(grid, role.parsed_rank_value) : null;
  const currentDivision =
    role.current_rank_value != null ? resolveDivisionFromRank(grid, role.current_rank_value) : null;

  // Which rank value to show as the primary label
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
        <span className="opacity-60">missing</span>
      ) : (
        <>
          {/* When overwriting: show current → new */}
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
        </>
      )}
    </div>
  );
}

function RankAutofillDialog({
  open,
  onOpenChange,
  preview,
  loadingPreview,
  applying,
  mode,
  onModeChange,
  overwriteExisting,
  onOverwriteChange,
  addToBalancer,
  onAddToBalancerChange,
  assignmentConfirmed,
  onAssignmentConfirmedChange,
  onApply
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: RegistrationRankAutofillResponse | undefined;
  loadingPreview: boolean;
  applying: boolean;
  mode: RegistrationRankAutofillMode;
  onModeChange: (mode: RegistrationRankAutofillMode) => void;
  overwriteExisting: boolean;
  onOverwriteChange: (checked: boolean) => void;
  addToBalancer: boolean;
  onAddToBalancerChange: (checked: boolean) => void;
  assignmentConfirmed: boolean;
  onAssignmentConfirmedChange: (checked: boolean) => void;
  onApply: () => void;
}) {
  const updatablePlayers =
    preview?.players.filter(
      (player) => player.status === "will_update" || player.status === "applied"
    ) ?? [];
  const skippedPlayers = preview?.players.filter((player) => player.status === "skipped") ?? [];
  const unchangedPlayers = preview?.players.filter((player) => player.status === "unchanged") ?? [];

  const isApplyDisabled =
    !preview ||
    (preview.role_updates === 0 && preview.balancer_additions === 0) ||
    !assignmentConfirmed ||
    loadingPreview ||
    applying;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-4xl flex-col gap-0 overflow-hidden border-border bg-popover p-0 text-white shadow-2xl shadow-black/50 sm:rounded-xl">
        {/* ── Header ── */}
        <DialogHeader className="shrink-0 border-b border-white/10 px-5 py-3.5 text-left">
          <div className="flex items-center justify-between gap-4">
            <div>
              <DialogTitle className="text-lg font-semibold tracking-tight text-white">
                Autofill parsed ranks
              </DialogTitle>
              <DialogDescription className="mt-0.5 text-xs text-white/40">
                Priority fallback per role. Main BattleTag only.
              </DialogDescription>
            </div>
            {/* Stats strip — visible once preview loads */}
            {preview && !loadingPreview && (
              <div className="flex shrink-0 items-center divide-x divide-white/10 rounded-lg border border-white/10 bg-white/[0.03]">
                {[
                  { label: "Players", value: preview.total_registrations, color: "" },
                  {
                    label: "Update",
                    value: preview.updatable_registrations,
                    color: "text-emerald-300"
                  },
                  { label: "Ranks", value: preview.role_updates, color: "text-emerald-300" },
                  {
                    label: "→ Balancer",
                    value: preview.balancer_additions,
                    color: "text-cyan-300"
                  },
                  {
                    label: "Skipped",
                    value: preview.skipped_registrations,
                    color: preview.skipped_registrations > 0 ? "text-orange-300" : ""
                  }
                ].map(({ label, value, color }) => (
                  <div key={label} className="px-3 py-2 text-center">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-white/35">
                      {label}
                    </div>
                    <div
                      className={cn(
                        "text-base font-semibold tabular-nums",
                        color || "text-white/80"
                      )}
                    >
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogHeader>

        {/* ── Settings strip ── */}
        <div className="shrink-0 border-b border-white/10 bg-white/[0.02] px-5 py-2.5">
          <div className="flex flex-wrap items-center gap-3">
            {/* Source priority mode */}
            <div className="flex rounded-lg border border-white/10 p-0.5">
              {(
                [
                  { value: "ow_first", label: "OW → balancer → analytics" },
                  { value: "balancer_first", label: "Balancer → analytics → OW" }
                ] as { value: RegistrationRankAutofillMode; label: string }[]
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onModeChange(value)}
                  disabled={loadingPreview || applying}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50",
                    mode === value
                      ? "bg-indigo-500/20 text-indigo-200"
                      : "text-white/50 hover:text-white/80"
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="h-5 w-px bg-white/10" aria-hidden="true" />

            {/* Overwrite checkbox */}
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={overwriteExisting}
                onCheckedChange={(checked) => onOverwriteChange(checked === true)}
                disabled={loadingPreview || applying}
                aria-label="Overwrite existing ranks"
              />
              <span className="text-xs text-white/65 select-none">Overwrite existing ranks</span>
            </label>

            {/* Add to balancer checkbox */}
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={addToBalancer}
                onCheckedChange={(checked) => onAddToBalancerChange(checked === true)}
                disabled={loadingPreview || applying}
                aria-label="Move eligible players to balancer"
              />
              <span className="text-xs text-white/65 select-none">Move eligible to balancer</span>
            </label>

            {loadingPreview && (
              <div className="ml-auto flex items-center gap-1.5 text-xs text-white/40">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading preview…
              </div>
            )}
          </div>
        </div>

        {/* ── Scrollable content ── */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!preview && !loadingPreview ? (
            <div className="flex h-32 items-center justify-center text-sm text-white/30">
              Preview is not loaded.
            </div>
          ) : preview ? (
            <div className="divide-y divide-white/[0.06]">
              {/* Will be assigned */}
              <div className="px-5 py-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                    Will be assigned
                  </span>
                  <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                    {updatablePlayers.length}
                  </span>
                </div>
                {updatablePlayers.length === 0 ? (
                  <p className="text-xs text-white/30">No ranks to update.</p>
                ) : (
                  <div className="overflow-hidden rounded-xl border border-white/10">
                    {updatablePlayers.map((player) => (
                      <div
                        key={player.registration_id}
                        className="flex min-w-0 items-center gap-3 border-b border-white/[0.06] px-3 py-2 last:border-b-0"
                      >
                        <div className="min-w-0 w-48 shrink-0">
                          <div className="truncate text-sm font-medium text-white/85">
                            {player.battle_tag ??
                              player.display_name ??
                              `#${player.registration_id}`}
                          </div>
                          <div className="flex items-center gap-1.5 text-[11px] text-white/30">
                            <span>#{player.registration_id}</span>
                            {player.will_add_to_balancer && (
                              <span className="rounded border border-cyan-400/20 bg-cyan-500/10 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-cyan-200">
                                → Balancer
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex min-w-0 flex-wrap gap-1.5">
                          {player.roles
                            .filter((r) => r.action === "set" || r.action === "overwrite")
                            .map((role) => (
                              <RankAutofillRolePill key={role.role} role={role} />
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Skipped + Already set — side by side */}
              <div className="grid gap-px lg:grid-cols-2">
                {/* Skipped */}
                <div className="px-5 py-3">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                      Skipped
                    </span>
                    {skippedPlayers.length > 0 && (
                      <span className="rounded-full bg-orange-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-orange-300">
                        {skippedPlayers.length}
                      </span>
                    )}
                  </div>
                  {skippedPlayers.length === 0 ? (
                    <p className="text-xs text-white/30">None skipped.</p>
                  ) : (
                    <div className="max-h-52 overflow-y-auto rounded-xl border border-white/10">
                      {skippedPlayers.map((player) => (
                        <div
                          key={player.registration_id}
                          className="border-b border-white/[0.06] px-3 py-2 last:border-b-0"
                        >
                          <div className="truncate text-xs font-medium text-white/75">
                            {player.battle_tag ??
                              player.display_name ??
                              `#${player.registration_id}`}
                          </div>
                          <div className="mt-0.5 text-[11px] leading-4 text-orange-200/70">
                            {player.reason ?? "Skipped"}
                          </div>
                          {player.will_add_to_balancer ? (
                            <div className="mt-0.5 text-[11px] text-cyan-200/70">
                              Will be moved to balancer.
                            </div>
                          ) : player.balancer_reason ? (
                            <div className="mt-0.5 text-[11px] text-white/30">
                              {player.balancer_reason}
                            </div>
                          ) : null}
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

                {/* Already set */}
                <div className="px-5 py-3 lg:border-l lg:border-white/[0.06]">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
                      Already set
                    </span>
                    {unchangedPlayers.length > 0 && (
                      <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold text-white/40">
                        {unchangedPlayers.length}
                      </span>
                    )}
                  </div>
                  {unchangedPlayers.length === 0 ? (
                    <p className="text-xs text-white/30">No unchanged registrations.</p>
                  ) : (
                    <div className="max-h-52 overflow-y-auto rounded-xl border border-white/10">
                      {unchangedPlayers.map((player) => (
                        <div
                          key={player.registration_id}
                          className="border-b border-white/[0.06] px-3 py-2 last:border-b-0"
                        >
                          <div className="truncate text-xs font-medium text-white/75">
                            {player.battle_tag ??
                              player.display_name ??
                              `#${player.registration_id}`}
                          </div>
                          <div className="mt-0.5 text-[11px] leading-4 text-white/35">
                            {player.reason ?? "No rank changes needed."}
                          </div>
                          {player.will_add_to_balancer ? (
                            <div className="mt-0.5 text-[11px] text-cyan-200/70">
                              Will be moved to balancer.
                            </div>
                          ) : player.balancer_reason ? (
                            <div className="mt-0.5 text-[11px] text-white/30">
                              {player.balancer_reason}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {/* ── Footer ── */}
        <div className="shrink-0 border-t border-white/10 px-5 py-3">
          <div className="flex items-center gap-3">
            <label className="flex flex-1 cursor-pointer items-center gap-2.5">
              <Checkbox
                checked={assignmentConfirmed}
                onCheckedChange={(checked) => onAssignmentConfirmedChange(checked === true)}
                disabled={
                  !preview ||
                  (preview.role_updates === 0 && preview.balancer_additions === 0) ||
                  loadingPreview ||
                  applying
                }
                aria-label="Confirm rank assignment"
              />
              <span className="text-xs text-white/60 select-none">
                Confirm assigning ranks to listed players
              </span>
            </label>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={applying}
            >
              Cancel
            </Button>
            <Button size="sm" onClick={onApply} disabled={isApplyDisabled}>
              {applying ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="mr-1.5 h-3.5 w-3.5" />
              )}
              Apply ranks
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function BalancerRegistrationsPage() {
  const tournamentId = useBalancerTournamentId();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<RegistrationStatusFilter>(
    (searchParams.get("status") as RegistrationStatusFilter | null) ?? "all"
  );
  const [inclusionFilter, setInclusionFilter] = useState<InclusionFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>(
    (searchParams.get("source") as SourceFilter | null) ?? "all"
  );
  const [groupBy, setGroupBy] = useState<RegistrationGroupingMode>(
    normalizeRegistrationGroupingMode(searchParams.get("group"))
  );
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [editingRegistration, setEditingRegistration] = useState<AdminRegistration | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [rankAutofillOpen, setRankAutofillOpen] = useState(false);
  const [autofillMode, setAutofillMode] = useState<RegistrationRankAutofillMode>("ow_first");
  const [overwriteExistingRanks, setOverwriteExistingRanks] = useState(false);
  const [addAutofilledPlayersToBalancer, setAddAutofilledPlayersToBalancer] = useState(false);
  const [rankAutofillConfirmed, setRankAutofillConfirmed] = useState(false);

  const toggleExpanded = (registrationId: number) =>
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(registrationId)) {
        next.delete(registrationId);
      } else {
        next.add(registrationId);
      }
      return next;
    });

  const [sortField, setSortField] = useState<string | null>("submitted");
  const [sortDescending, setSortDescending] = useState<boolean>(true);

  const handleSort = (fieldId: string) => {
    if (sortField === fieldId) {
      setSortDescending((prev) => !prev);
    } else {
      setSortField(fieldId);
      setSortDescending(fieldId === "submitted" || fieldId === "reviewed");
    }
  };

  const registrationsQuery = useQuery({
    queryKey: [
      "balancer-admin",
      "registrations",
      tournamentId,
      statusFilter,
      inclusionFilter,
      sourceFilter
    ],
    queryFn: () =>
      balancerAdminService.listRegistrations(tournamentId as number, {
        status_filter: statusFilter === "all" ? undefined : statusFilter,
        inclusion_filter: inclusionFilter === "all" ? undefined : inclusionFilter,
        source_filter: sourceFilter === "all" ? undefined : sourceFilter,
        include_deleted: false
      }),
    enabled: tournamentId !== null
  });

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  const publicFormQuery = useQuery({
    queryKey: ["registration-form-public", tournamentId],
    queryFn: () => registrationService.getForm(tournamentId as number),
    enabled: tournamentId !== null
  });

  // Adapt the admin form into the public RegistrationForm shape used by the
  // shared RoleStep / sub-role catalog, so admin role editing is data-driven.
  const roleForm: RegistrationForm = useMemo(() => {
    const data = publicFormQuery.data;
    if (!data) {
      return ADMIN_ROLE_FORM;
    }
    return data;
  }, [publicFormQuery.data]);
  const subroleCatalog = roleForm.subrole_catalog;

  const requireOpenProfile = formQuery.data?.require_open_profile ?? false;

  const allColumns = useMemo(
    () => buildBalancerRegistrationColumns(subroleCatalog, requireOpenProfile),
    [subroleCatalog, requireOpenProfile]
  );
  const { visibleColumns, visibility, toggleColumn, resetToDefaults } = useColumnVisibility(
    "balancer-registrations-table-columns",
    allColumns
  );

  const customStatusesQuery = useQuery({
    queryKey: ["balancer-admin", "status-catalog", workspaceId],
    queryFn: () => balancerAdminService.listStatusCatalog(workspaceId as number),
    enabled: workspaceId !== null
  });
  const registrationStatusOptions = useMemo(
    () => mergeStatusOptions("registration", customStatusesQuery.data),
    [customStatusesQuery.data]
  );
  const balancerStatusOptions = useMemo(
    () => mergeStatusOptions("balancer", customStatusesQuery.data),
    [customStatusesQuery.data]
  );

  const invalidateRegistrations = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["balancer-admin", "registrations", tournamentId]
    });
  };

  const createMutation = useMutation({
    mutationFn: (payload: any) =>
      balancerAdminService.createManualRegistration(tournamentId as number, payload),
    onSuccess: async () => {
      await invalidateRegistrations();
      setCreateOpen(false);
      notify.success("Manual registration created");
    }
  });

  const updateMutation = useMutation({
    mutationFn: (payload: any) => {
      if (!editingRegistration) {
        throw new Error("No registration selected");
      }
      return balancerAdminService.updateRegistration(editingRegistration.id, payload);
    },
    onSuccess: async () => {
      await invalidateRegistrations();
      setEditingRegistration(null);
      notify.success("Registration updated");
    }
  });

  const approveMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.approveRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Registration approved");
    }
  });

  const rejectMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.rejectRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Registration rejected");
    }
  });

  const withdrawMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.withdrawRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Registration withdrawn");
    }
  });

  const restoreMutation = useMutation({
    mutationFn: (registrationId: number) =>
      balancerAdminService.restoreRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Registration restored");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (registrationId: number) => balancerAdminService.deleteRegistration(registrationId),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Registration deleted");
    }
  });

  const bulkApproveMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.bulkApproveRegistrations(
        tournamentId as number,
        Array.from(selectedIds)
      ),
    onSuccess: async (result) => {
      await invalidateRegistrations();
      setSelectedIds(new Set());
      notify.success(`${result.approved} approved, ${result.skipped} skipped`);
    }
  });

  const balancerStatusMutation = useMutation({
    mutationFn: ({
      registrationId,
      balancerStatus
    }: {
      registrationId: number;
      balancerStatus: string;
    }) => balancerAdminService.setBalancerStatus(registrationId, balancerStatus),
    onSuccess: async () => {
      await invalidateRegistrations();
      notify.success("Balancer status updated");
    }
  });

  const checkInMutation = useMutation({
    mutationFn: ({ registrationId, checkedIn }: { registrationId: number; checkedIn: boolean }) =>
      balancerAdminService.checkInRegistration(registrationId, checkedIn),
    onSuccess: async (_, variables) => {
      await invalidateRegistrations();
      notify.success(variables.checkedIn ? "Checked in" : "Check-in removed");
    }
  });

  const bulkAddToBalancerMutation = useMutation({
    mutationFn: () =>
      balancerAdminService.bulkAddToBalancer(tournamentId as number, Array.from(selectedIds)),
    onSuccess: async (result) => {
      await invalidateRegistrations();
      setSelectedIds(new Set());
      notify.success(`${result.updated} added to balancer, ${result.skipped} skipped`);
    }
  });

  const exportToUsersMutation = useMutation({
    mutationFn: () => balancerAdminService.exportRegistrationsToUsers(tournamentId as number),
    onSuccess: (result) => {
      notify.success("Export complete", {
        description: `${result.processed} processed, ${result.skipped} skipped (${result.total} total)`
      });
    }
  });

  const rankAutofillPreviewMutation = useMutation({
    mutationFn: ({ overwriteExisting, addToBalancer, mode }: RankAutofillPreviewOptions) => {
      if (!tournamentId) {
        throw new Error("Select a tournament first");
      }
      return balancerAdminService.previewRegistrationRankAutofill(tournamentId, {
        overwrite_existing: overwriteExisting,
        add_to_balancer: addToBalancer,
        mode
      });
    },
    onSuccess: () => {
      setRankAutofillConfirmed(false);
      setRankAutofillOpen(true);
    }
  });

  const rankAutofillApplyMutation = useMutation({
    mutationFn: () => {
      if (!tournamentId) {
        throw new Error("Select a tournament first");
      }
      return balancerAdminService.applyRegistrationRankAutofill(tournamentId, {
        overwrite_existing: overwriteExistingRanks,
        add_to_balancer: addAutofilledPlayersToBalancer,
        mode: autofillMode
      });
    },
    onSuccess: async (result) => {
      await invalidateRegistrations();
      setRankAutofillOpen(false);
      notify.success("Ranks autofilled", {
        description:
          `${result.applied_registrations} player${
            result.applied_registrations === 1 ? "" : "s"
          }, ${result.role_updates} role rank${
            result.role_updates === 1 ? "" : "s"
          } updated. ${result.skipped_registrations} skipped.` +
          (result.balancer_additions > 0 ? ` ${result.balancer_additions} moved to balancer.` : "")
      });
    }
  });

  const openRankAutofillPreview = () => {
    setOverwriteExistingRanks(false);
    setAddAutofilledPlayersToBalancer(false);
    setRankAutofillConfirmed(false);
    rankAutofillPreviewMutation.mutate({
      overwriteExisting: false,
      addToBalancer: false,
      mode: autofillMode
    });
  };

  const handleAutofillModeChange = (mode: RegistrationRankAutofillMode) => {
    setAutofillMode(mode);
    setRankAutofillConfirmed(false);
    rankAutofillPreviewMutation.mutate({
      overwriteExisting: overwriteExistingRanks,
      addToBalancer: addAutofilledPlayersToBalancer,
      mode
    });
  };

  const handleRankOverwriteChange = (checked: boolean) => {
    setOverwriteExistingRanks(checked);
    setRankAutofillConfirmed(false);
    rankAutofillPreviewMutation.mutate({
      overwriteExisting: checked,
      addToBalancer: addAutofilledPlayersToBalancer,
      mode: autofillMode
    });
  };

  const handleAddToBalancerChange = (checked: boolean) => {
    setAddAutofilledPlayersToBalancer(checked);
    setRankAutofillConfirmed(false);
    rankAutofillPreviewMutation.mutate({
      overwriteExisting: overwriteExistingRanks,
      addToBalancer: checked,
      mode: autofillMode
    });
  };

  const registrations = registrationsQuery.data ?? [];
  const filteredRegistrations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    let result = registrations;
    if (query) {
      result = registrations.filter((registration) =>
        allColumns.some((column) => {
          if (!column.searchValue) {
            return false;
          }
          const value = column.searchValue(registration);
          return value?.toLowerCase().includes(query) ?? false;
        })
      );
    }

    if (!sortField) {
      return result;
    }

    return [...result].sort((a, b) => {
      let valA: any = null;
      let valB: any = null;

      switch (sortField) {
        case "participant":
          valA = a.battle_tag || a.display_name || "";
          valB = b.battle_tag || b.display_name || "";
          break;
        case "smurfs":
          valA = (a.smurf_tags_json || []).join(" ");
          valB = (b.smurf_tags_json || []).join(" ");
          break;
        case "roles": {
          const getHighestRank = (reg: AdminRegistration) => {
            const ranks = reg.roles
              .filter((r) => r.is_active && r.rank_value != null)
              .map((r) => r.rank_value as number);
            return ranks.length > 0 ? Math.max(...ranks) : 0;
          };
          valA = getHighestRank(a);
          valB = getHighestRank(b);
          break;
        }
        case "status":
          valA = a.status || "";
          valB = b.status || "";
          break;
        case "balancer":
          valA = a.balancer_status || "";
          valB = b.balancer_status || "";
          break;
        case "checkin":
          valA = a.checked_in ? 1 : 0;
          valB = b.checked_in ? 1 : 0;
          break;
        case "admission": {
          const getAdmissionScore = (reg: AdminRegistration) => {
            const isProfileClosed = requireOpenProfile && reg.profiles_open === false;
            const isApprovedAndReady =
              reg.status === "approved" && reg.balancer_status === "ready" && !isProfileClosed;
            if (!isApprovedAndReady) return 0;
            return reg.checked_in ? 2 : 1;
          };
          valA = getAdmissionScore(a);
          valB = getAdmissionScore(b);
          break;
        }
        case "profile":
          valA = a.profiles_open === true ? 2 : a.profiles_open === false ? 1 : 0;
          valB = b.profiles_open === true ? 2 : b.profiles_open === false ? 1 : 0;
          break;
        case "submitted":
          valA = a.submitted_at ? new Date(a.submitted_at).getTime() : 0;
          valB = b.submitted_at ? new Date(b.submitted_at).getTime() : 0;
          break;
        case "source":
          valA = a.source || "";
          valB = b.source || "";
          break;
        case "notes":
          valA = a.notes || "";
          valB = b.notes || "";
          break;
        case "admin_notes":
          valA = a.admin_notes || "";
          valB = b.admin_notes || "";
          break;
        case "reviewed":
          valA = a.reviewed_at ? new Date(a.reviewed_at).getTime() : 0;
          valB = b.reviewed_at ? new Date(b.reviewed_at).getTime() : 0;
          break;
        case "excluded":
          valA = a.exclude_from_balancer ? 1 : 0;
          valB = b.exclude_from_balancer ? 1 : 0;
          break;
        default:
          return 0;
      }

      if (typeof valA === "string" && typeof valB === "string") {
        return sortDescending
          ? valB.localeCompare(valA, undefined, { sensitivity: "base", numeric: true })
          : valA.localeCompare(valB, undefined, { sensitivity: "base", numeric: true });
      }

      if (valA < valB) return sortDescending ? 1 : -1;
      if (valA > valB) return sortDescending ? -1 : 1;
      return 0;
    });
  }, [allColumns, registrations, searchQuery, sortField, sortDescending, requireOpenProfile]);
  const groupedRegistrations = useMemo(
    () => groupRegistrations(filteredRegistrations, groupBy, requireOpenProfile),
    [filteredRegistrations, groupBy, requireOpenProfile]
  );

  const selectableIds = useMemo(
    () =>
      filteredRegistrations
        .filter((registration) => registration.status === "pending")
        .map((registration) => registration.id),
    [filteredRegistrations]
  );

  const allSelectableRowsChecked =
    selectableIds.length > 0 &&
    selectableIds.every((registrationId) => selectedIds.has(registrationId));

  const pendingCount = registrations.filter(
    (registration) => registration.status === "pending"
  ).length;
  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the sidebar before managing registrations.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <Card className="flex min-h-0 flex-col overflow-hidden">
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Registrations</CardTitle>
              <CardDescription>
                {pendingCount > 0 ? `${pendingCount} pending. ` : null}
                Showing {filteredRegistrations.length} of {registrations.length}.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={openRankAutofillPreview}
                disabled={
                  rankAutofillPreviewMutation.isPending || rankAutofillApplyMutation.isPending
                }
              >
                {rankAutofillPreviewMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" />
                )}
                Autofill ranks
              </Button>
              <Button
                variant="outline"
                onClick={() => exportToUsersMutation.mutate()}
                disabled={exportToUsersMutation.isPending}
              >
                {exportToUsersMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                Export to analytics
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setCreateOpen(true);
                }}
              >
                <UserPlus className="mr-2 h-4 w-4" />
                Create registration
              </Button>
              {selectedIds.size > 0 ? (
                <>
                  <Button
                    onClick={() => bulkApproveMutation.mutate()}
                    disabled={bulkApproveMutation.isPending}
                  >
                    {bulkApproveMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="mr-2 h-4 w-4" />
                    )}
                    Approve {selectedIds.size}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => bulkAddToBalancerMutation.mutate()}
                    disabled={bulkAddToBalancerMutation.isPending}
                  >
                    {bulkAddToBalancerMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="mr-2 h-4 w-4" />
                    )}
                    Add to Balancer {selectedIds.size}
                  </Button>
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/30" />
              <Input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search registrations"
                className="pl-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value)}>
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectGroup>
                  <SelectLabel>System</SelectLabel>
                  {registrationStatusOptions.system.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
                {registrationStatusOptions.custom.length > 0 ? (
                  <SelectGroup>
                    <SelectLabel>Custom</SelectLabel>
                    {registrationStatusOptions.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ) : null}
              </SelectContent>
            </Select>
            <Select
              value={inclusionFilter}
              onValueChange={(value) => setInclusionFilter(value as InclusionFilter)}
            >
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Participation" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All participation</SelectItem>
                <SelectItem value="included">Included</SelectItem>
                <SelectItem value="excluded">Excluded</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={sourceFilter}
              onValueChange={(value) => setSourceFilter(value as SourceFilter)}
            >
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Source" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="manual">Manual</SelectItem>
                <SelectItem value="google_sheets">Google Sheets</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={groupBy}
              onValueChange={(value) => setGroupBy(value as RegistrationGroupingMode)}
            >
              <SelectTrigger className="w-[190px]">
                <SelectValue placeholder="Group by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No grouping</SelectItem>
                <SelectItem value="check_in">Group by check-in</SelectItem>
                <SelectItem value="balancer_status">Group by balancer</SelectItem>
                <SelectItem value="admission">Group by admission</SelectItem>
              </SelectContent>
            </Select>
            <BalancerRegistrationsColumnPicker
              columns={allColumns}
              visibility={visibility}
              onToggle={toggleColumn}
              onReset={resetToDefaults}
            />
          </div>
        </CardHeader>

        <CardContent className="min-h-0 flex-1 overflow-auto">
          <div className="overflow-x-auto overflow-hidden rounded-xl border border-white/[0.07]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02]">
                  <th className="w-10 px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-white/40">
                    <Checkbox
                      checked={allSelectableRowsChecked}
                      onCheckedChange={(checked) =>
                        setSelectedIds((current) => {
                          const next = new Set(current);
                          if (checked) {
                            selectableIds.forEach((registrationId) => next.add(registrationId));
                          } else {
                            selectableIds.forEach((registrationId) => next.delete(registrationId));
                          }
                          return next;
                        })
                      }
                      disabled={selectableIds.length === 0}
                      aria-label="Select visible pending registrations"
                    />
                  </th>
                  {visibleColumns.map((column) => {
                    const isSorted = sortField === column.id;
                    return (
                      <th
                        key={column.id}
                        onClick={() => handleSort(column.id)}
                        className={cn(
                          "group cursor-pointer select-none px-3 py-2.5 text-xs font-medium uppercase tracking-wider text-white/40 hover:bg-white/[0.01] hover:text-white/70 transition-colors",
                          RESPONSIVE_CLASS[column.responsive ?? "always"],
                          column.widthClass
                        )}
                      >
                        <div
                          className={cn(
                            "flex items-center gap-1",
                            ALIGN_CLASS[column.align ?? "left"] === "text-center"
                              ? "justify-center"
                              : ALIGN_CLASS[column.align ?? "left"] === "text-right"
                                ? "justify-end"
                                : "justify-start"
                          )}
                        >
                          <span>{column.label}</span>
                          <span className="shrink-0">
                            {isSorted ? (
                              sortDescending ? (
                                <ArrowDown className="size-3 text-emerald-400" />
                              ) : (
                                <ArrowUp className="size-3 text-emerald-400" />
                              )
                            ) : (
                              <ArrowUpDown className="size-3 opacity-0 group-hover:opacity-100 transition-opacity text-white/20" />
                            )}
                          </span>
                        </div>
                      </th>
                    );
                  })}
                  <th className="w-[112px] px-3 py-2.5 text-right text-xs font-medium uppercase tracking-wider text-white/40">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredRegistrations.length === 0 ? (
                  <tr>
                    <td
                      colSpan={visibleColumns.length + 2}
                      className="py-10 text-center text-sm text-white/40"
                    >
                      No registrations match the current filters.
                    </td>
                  </tr>
                ) : (
                  groupedRegistrations.map((group) => (
                    <Fragment key={group.key}>
                      {groupBy !== "none" ? (
                        <tr className="border-b border-white/[0.07] bg-white/[0.035]">
                          <td
                            colSpan={visibleColumns.length + 2}
                            className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-white/55"
                          >
                            <span className="text-white/80">{group.label}</span>
                            <span className="ml-2 text-white/35">
                              {group.registrations.length}{" "}
                              {group.registrations.length === 1 ? "registration" : "registrations"}
                            </span>
                          </td>
                        </tr>
                      ) : null}
                      {group.registrations.map((registration, index) => {
                        const selectable = registration.status === "pending";
                        const statusConfig =
                          STATUS_CONFIG[registration.status] ?? STATUS_CONFIG.pending;
                        const StatusIcon = statusConfig.icon;
                        const inBalancer = registration.balancer_status === "ready";
                        const isExpanded = expandedIds.has(registration.id);
                        return (
                          <Fragment key={registration.id}>
                            <tr className="border-b border-white/4 transition-colors hover:bg-white/[0.02]">
                              <td className="px-3 py-2.5 align-top">
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => toggleExpanded(registration.id)}
                                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-white/40 hover:bg-white/5 hover:text-white"
                                    aria-label={isExpanded ? "Collapse details" : "Expand details"}
                                    aria-expanded={isExpanded}
                                  >
                                    {isExpanded ? (
                                      <ChevronDown className="h-4 w-4" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4" />
                                    )}
                                  </button>
                                  {selectable ? (
                                    <Checkbox
                                      checked={selectedIds.has(registration.id)}
                                      onCheckedChange={(checked) =>
                                        setSelectedIds((current) => {
                                          const next = new Set(current);
                                          if (checked) {
                                            next.add(registration.id);
                                          } else {
                                            next.delete(registration.id);
                                          }
                                          return next;
                                        })
                                      }
                                      aria-label={`Select registration ${registration.id}`}
                                    />
                                  ) : null}
                                </div>
                              </td>
                              {visibleColumns.map((column) => (
                                <td
                                  key={column.id}
                                  className={cn(
                                    "px-3 py-2.5 align-top",
                                    RESPONSIVE_CLASS[column.responsive ?? "always"],
                                    ALIGN_CLASS[column.align ?? "left"],
                                    column.widthClass
                                  )}
                                >
                                  {column.render(registration, index)}
                                </td>
                              ))}
                              <td className="px-3 py-2.5 align-top">
                                <RegistrationRowActions
                                  registration={registration}
                                  onEdit={(selectedRegistration) => {
                                    setEditingRegistration(selectedRegistration);
                                  }}
                                  onApprove={(registrationId) =>
                                    approveMutation.mutate(registrationId)
                                  }
                                  onReject={(registrationId) =>
                                    rejectMutation.mutate(registrationId)
                                  }
                                  onToggleBalancer={(selectedRegistration) =>
                                    balancerStatusMutation.mutate({
                                      registrationId: selectedRegistration.id,
                                      balancerStatus:
                                        selectedRegistration.balancer_status === "ready"
                                          ? "not_in_balancer"
                                          : "ready"
                                    })
                                  }
                                  onToggleCheckIn={(selectedRegistration) =>
                                    checkInMutation.mutate({
                                      registrationId: selectedRegistration.id,
                                      checkedIn: !selectedRegistration.checked_in
                                    })
                                  }
                                  onWithdraw={(registrationId) =>
                                    withdrawMutation.mutate(registrationId)
                                  }
                                  onRestore={(registrationId) =>
                                    restoreMutation.mutate(registrationId)
                                  }
                                  onDelete={(registrationId) =>
                                    deleteMutation.mutate(registrationId)
                                  }
                                />
                              </td>
                              {false && (
                                <>
                                  <TableCell>
                                    <div className="space-y-1">
                                      <div className="font-medium">
                                        {registration.battle_tag ??
                                          registration.display_name ??
                                          `Registration #${registration.id}`}
                                      </div>
                                      <div className="text-xs text-muted-foreground">
                                        {[registration.discord_nick, registration.twitch_nick]
                                          .filter(Boolean)
                                          .join(" · ") ||
                                          registration.source_record_key ||
                                          "-"}
                                      </div>
                                    </div>
                                  </TableCell>
                                  <TableCell>
                                    <SourceBadge source={registration.source} />
                                  </TableCell>
                                  <TableCell>
                                    <RolesCell
                                      roles={registration.roles}
                                      catalog={subroleCatalog}
                                    />
                                  </TableCell>
                                  <TableCell>
                                    <Badge variant="outline" className={statusConfig.className}>
                                      <StatusIcon className="mr-1 h-3.5 w-3.5" />
                                      {statusConfig.label}
                                    </Badge>
                                  </TableCell>
                                  <TableCell>
                                    <BalancerBadge registration={registration} />
                                  </TableCell>
                                  <TableCell>
                                    <CheckInBadge registration={registration} />
                                  </TableCell>
                                  <TableCell className="text-sm text-muted-foreground">
                                    {formatSubmittedAt(registration.submitted_at)}
                                  </TableCell>
                                  <TableCell>
                                    <div className="flex flex-wrap gap-2">
                                      {registration.status === "pending" ? (
                                        <>
                                          <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => approveMutation.mutate(registration.id)}
                                          >
                                            <Check className="mr-1.5 h-3.5 w-3.5" />
                                            Approve
                                          </Button>
                                          <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => rejectMutation.mutate(registration.id)}
                                          >
                                            <X className="mr-1.5 h-3.5 w-3.5" />
                                            Reject
                                          </Button>
                                        </>
                                      ) : null}
                                      {registration.status !== "withdrawn" ? (
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => {
                                            setEditingRegistration(registration);
                                          }}
                                        >
                                          <Pencil className="mr-1.5 h-3.5 w-3.5" />
                                          Edit
                                        </Button>
                                      ) : null}
                                      {registration.status === "approved" ? (
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() =>
                                            balancerStatusMutation.mutate({
                                              registrationId: registration.id,
                                              balancerStatus: inBalancer
                                                ? "not_in_balancer"
                                                : "ready"
                                            })
                                          }
                                        >
                                          {inBalancer ? (
                                            <ShieldX className="mr-1.5 h-3.5 w-3.5" />
                                          ) : (
                                            <Check className="mr-1.5 h-3.5 w-3.5" />
                                          )}
                                          {inBalancer ? "Remove from Balancer" : "Add to Balancer"}
                                        </Button>
                                      ) : null}
                                      {registration.status === "approved" ? (
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() =>
                                            checkInMutation.mutate({
                                              registrationId: registration.id,
                                              checkedIn: !registration.checked_in
                                            })
                                          }
                                        >
                                          <Check className="mr-1.5 h-3.5 w-3.5" />
                                          {registration.checked_in ? "Uncheck-in" : "Check-in"}
                                        </Button>
                                      ) : null}
                                      {registration.status === "withdrawn" ? (
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => restoreMutation.mutate(registration.id)}
                                        >
                                          <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                                          Restore
                                        </Button>
                                      ) : (
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => withdrawMutation.mutate(registration.id)}
                                        >
                                          <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                                          Withdraw
                                        </Button>
                                      )}
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => deleteMutation.mutate(registration.id)}
                                      >
                                        <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                                        Delete
                                      </Button>
                                    </div>
                                  </TableCell>
                                </>
                              )}
                            </tr>
                            {isExpanded ? (
                              <tr className="border-b border-white/[0.06] bg-white/[0.015]">
                                <td colSpan={visibleColumns.length + 2} className="px-4 py-4">
                                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
                                    <div className="space-y-2">
                                      <div className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                                        Rank history
                                      </div>
                                      <BattleTagRankHistory
                                        userId={registration.user_id}
                                        battleTag={registration.battle_tag}
                                      />
                                    </div>
                                    <dl className="space-y-2 text-xs text-white/70">
                                      <div className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                                        Details
                                      </div>
                                      <div>
                                        <dt className="mb-1 text-white/40">Declared roles</dt>
                                        <dd>
                                          <RolesCell
                                            roles={registration.roles}
                                            catalog={subroleCatalog}
                                          />
                                        </dd>
                                      </div>
                                      {registration.smurf_tags_json.length > 0 ? (
                                        <div className="flex justify-between gap-3">
                                          <dt className="text-white/40">Smurfs</dt>
                                          <dd className="text-right">
                                            {registration.smurf_tags_json.join(", ")}
                                          </dd>
                                        </div>
                                      ) : null}
                                      {registration.discord_nick || registration.twitch_nick ? (
                                        <div className="flex justify-between gap-3">
                                          <dt className="text-white/40">Contact</dt>
                                          <dd className="text-right">
                                            {[registration.discord_nick, registration.twitch_nick]
                                              .filter(Boolean)
                                              .join(" · ")}
                                          </dd>
                                        </div>
                                      ) : null}
                                      <div className="flex justify-between gap-3">
                                        <dt className="text-white/40">Source</dt>
                                        <dd className="text-right">{registration.source}</dd>
                                      </div>
                                      <div className="flex justify-between gap-3">
                                        <dt className="text-white/40">Submitted</dt>
                                        <dd className="text-right">
                                          {formatSubmittedAt(registration.submitted_at)}
                                        </dd>
                                      </div>
                                      {registration.reviewed_at ? (
                                        <div className="flex justify-between gap-3">
                                          <dt className="text-white/40">Reviewed</dt>
                                          <dd className="text-right">
                                            {formatSubmittedAt(registration.reviewed_at)}
                                            {registration.reviewed_by_username
                                              ? ` · ${registration.reviewed_by_username}`
                                              : ""}
                                          </dd>
                                        </div>
                                      ) : null}
                                      {registration.notes ? (
                                        <div>
                                          <dt className="text-white/40">Notes</dt>
                                          <dd className="mt-0.5">{registration.notes}</dd>
                                        </div>
                                      ) : null}
                                      {registration.admin_notes ? (
                                        <div>
                                          <dt className="text-white/40">Admin notes</dt>
                                          <dd className="mt-0.5">{registration.admin_notes}</dd>
                                        </div>
                                      ) : null}
                                    </dl>
                                  </div>
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <RankAutofillDialog
        open={rankAutofillOpen}
        onOpenChange={setRankAutofillOpen}
        preview={rankAutofillPreviewMutation.data}
        loadingPreview={rankAutofillPreviewMutation.isPending}
        applying={rankAutofillApplyMutation.isPending}
        mode={autofillMode}
        onModeChange={handleAutofillModeChange}
        overwriteExisting={overwriteExistingRanks}
        onOverwriteChange={handleRankOverwriteChange}
        addToBalancer={addAutofilledPlayersToBalancer}
        onAddToBalancerChange={handleAddToBalancerChange}
        assignmentConfirmed={rankAutofillConfirmed}
        onAssignmentConfirmedChange={setRankAutofillConfirmed}
        onApply={() => rankAutofillApplyMutation.mutate()}
      />

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
        }}
      >
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-border bg-popover p-0 text-white shadow-2xl shadow-black/50 sm:rounded-xl">
          <DialogHeader className="border-b border-white/10 px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-white">
              Create Manual Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-white/50">
              Open the same multi-step visual shell used by the public flow, but keep every admin
              field available in one fixed editor.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            <UnifiedRegistrationForm
              mode="admin"
              tournamentId={tournamentId as number}
              workspaceId={workspaceId as number}
              formConfig={roleForm}
              onSubmit={async (payload) => {
                await createMutation.mutateAsync(payload);
              }}
              onCancel={() => {
                setCreateOpen(false);
              }}
              submitPending={createMutation.isPending}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingRegistration !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditingRegistration(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl gap-0 overflow-hidden border-border bg-popover p-0 text-white shadow-2xl shadow-black/50 sm:rounded-xl">
          <DialogHeader className="border-b border-white/10 px-4 py-3.5 text-left sm:px-5">
            <DialogTitle className="text-xl font-semibold tracking-tight text-white">
              Edit Registration
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl text-sm leading-5 text-white/50">
              Update balancer-facing participant data in the fixed admin editor, while keeping the
              public multi-step look and hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto px-4 py-3.5 sm:px-5">
            {editingRegistration && (
              <UnifiedRegistrationForm
                mode="admin"
                tournamentId={tournamentId as number}
                workspaceId={workspaceId as number}
                formConfig={roleForm}
                initialData={editingRegistration}
                onSubmit={async (payload) => {
                  await updateMutation.mutateAsync(payload);
                }}
                onCancel={() => {
                  setEditingRegistration(null);
                }}
                submitPending={updateMutation.isPending}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
