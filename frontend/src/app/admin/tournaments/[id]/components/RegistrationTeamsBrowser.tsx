"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Ban,
  ChevronDown,
  Crown,
  FolderInput,
  LifeBuoy,
  Loader2,
  Pencil,
  RotateCcw,
  Unlock,
  UserPlus,
  X,
  type LucideIcon
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { AdminCombobox, AdminComboboxCheck } from "@/components/admin/AdminCombobox";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { BulkBar } from "@/components/admin/BulkBar";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { adminColumnMeta } from "@/components/admin/admin-table-columns";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { ConfirmDialog, type ConfirmIntent } from "@/components/admin/kit/ConfirmDialog";
import { createKebabColumn, type KebabAction } from "@/components/admin/kit/kebab-column";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import { type Tone } from "@/components/admin/tone";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { formatShortfall } from "@/lib/registration-team-shortfall";
import {
  REGISTRATION_TEAM_ERROR_CODES,
  translateRegistrationTeamError
} from "@/lib/registration-team-errors";
import { getRegistrationTeamStatus } from "@/lib/registration-team-tone";
import { ROSTER_SLOT_CODES } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";
import type {
  RegistrationTeam,
  RegistrationTeamExportResult,
  RegistrationTeamInvite,
  RegistrationTeamMember
} from "@/types/registration-team.types";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";

/**
 * Organizer view of the registered teams (§8 of the team-registration design).
 *
 * The reason this screen exists is the shortfall: a captain's team enters the
 * tournament only with a full roster, so "who is still incomplete" is the one
 * question an organizer asks before formation closes — it gets a column of its
 * own rather than hiding behind a status badge.
 *
 * It is a T2 browser (DESIGN.md): `AdminDataTable` rows, `AdminFilterBar` chips
 * that live in the URL, one always-visible kebab per row, and the row detail in
 * `AdminInspector` at `?id=`. Unlike the public roster it also shows the
 * invites, and it is the only place that can reject a team or materialize the
 * complete ones into `tournament.team` (the export). Both are server-authorized;
 * the actions follow the same permissions, so a caller is never offered an
 * action that will 403.
 */

const EXPIRY_STAMP = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit"
} as const;

const EXPORT_SKIP_CODES = ["team_incomplete", "team_empty", "team_waitlisted", "team_subscription_uncovered"] as const;

/** The states the ledger names. Anything outside it renders raw: the server
 *  derives `expired` from a pending row past its clock and may add more, and an
 *  untranslated word beats a missing message path on screen. */
const HISTORY_STATES = ["pending", "accepted", "declined", "revoked", "expired"] as const;

const INVITE_TONE: Record<(typeof HISTORY_STATES)[number], Tone> = {
  pending: "warning",
  accepted: "success",
  declined: "danger",
  revoked: "neutral",
  expired: "neutral"
};

function inviteTone(state: string): Tone {
  const known = HISTORY_STATES.find((candidate) => candidate === state);
  return known ? INVITE_TONE[known] : "neutral";
}

/** Lifecycle tone for the admin's own pill vocabulary. The public surfaces use
 *  `REGISTRATION_TEAM_STATUS_TONE` (raw classes); `StatusPill` takes a `Tone`. */
const TEAM_STATUS_TONE: Record<string, Tone> = {
  forming: "warning",
  complete: "success",
  exported: "info",
  rejected: "danger",
  disbanded: "neutral"
};

const ADMISSION_TONE: Record<string, Tone> = {
  pending: "warning",
  accepted: "success",
  waitlisted: "neutral"
};

function memberName(member: RegistrationTeamMember): string {
  return member.display_name ?? member.battle_tag ?? `#${member.registration_id}`;
}

/** The one member every organizer view identifies a team by. */
function captainOf(team: RegistrationTeam): RegistrationTeamMember | undefined {
  return team.members.find((member) => member.is_captain);
}

/**
 * Starters on the roster, and how many the tournament's shape asks for.
 *
 * `required` is not a field: the server sends what is still open, so the target
 * is the starters already placed plus those holes.
 */
function rosterCounts(team: RegistrationTeam): { starters: number; required: number } {
  const starters = team.members.filter((member) => !member.is_substitute).length;
  const open = Object.values(team.open_slots).reduce((sum, count) => sum + (count ?? 0), 0);
  return { starters, required: starters + open };
}

/**
 * An invite an organizer can still withdraw: anything terminal, or a pending
 * one already past its clock, is out of everybody's hands.
 *
 * Its own function because the clock is read here: `Date.now()` inside the JSX
 * is an impure render (`react-hooks/purity`), same as `getApiKeyStatus` in
 * `access/api-keys`.
 */
function isLiveInvite(invite: RegistrationTeamInvite): boolean {
  return (
    invite.state === "pending" &&
    (!invite.expires_at || new Date(invite.expires_at).getTime() > Date.now())
  );
}

/**
 * Captain / substitute marker.
 *
 * The glyph replaces the word: on a table whose whole job is fitting every team
 * on one screen, "Captain" spelled out cost more width than the name beside it.
 * Same vocabulary as the public roster (`RegistrationTeamsList`), and the name
 * is still announced — hidden text, not a missing label.
 */
function RosterMark({
  icon: Icon,
  label,
  className
}: Readonly<{ icon: LucideIcon; label: string; className?: string }>) {
  return (
    <span className={cn("inline-flex shrink-0", className)} title={label}>
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

/**
 * One team's whole invite ledger, organizer side.
 *
 * Collapsed and unfetched until asked for: the chips above already answer the
 * usual question, and this read exists for the rarer one — was that slot
 * refused, or did the link merely lapse. The chips cannot answer it because the
 * team read returns only LIVE invites (a terminal row there would hold a roster
 * slot open).
 *
 * Its own component because a hook cannot run inside the team loop, and
 * deliberately local to this file: the captain's side has a separate one, and
 * sharing would couple two surfaces that ship independently.
 */
function TeamInviteHistory({
  tournamentId,
  workspaceId,
  teamId,
  meta
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
  teamId: number;
  /** Rendered on the trigger's own line — a second full-width row for one
   *  short counter is the kind of thing that made this panel three screens. */
  meta?: ReactNode;
}>) {
  const t = useTranslations("registrationTeams");
  const tErr = useTranslations("registrationTeams.errors");
  const format = useFormatter();
  const [open, setOpen] = useState(false);

  const historyQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId),
    queryFn: () => registrationTeamService.listInviteHistoryAdmin(tournamentId, teamId),
    // Nothing pays for the ledger until someone opens it.
    enabled: open
  });

  const history = historyQuery.data;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="flex items-center justify-between gap-2">
        {meta}
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-6 gap-1 px-1.5 text-caption font-normal text-muted-foreground"
          >
            {t("history.toggle")}
            <ChevronDown
              aria-hidden
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className="space-y-1 pt-2">
        {historyQuery.isError ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>
              {translateRegistrationTeamError(tErr, historyQuery.error, t("admin.loadFailed"))}
              <Button type="button" variant="outline" size="sm" className="ml-2" disabled={historyQuery.isFetching} onClick={() => void historyQuery.refetch()}>{t("admin.retry")}</Button>
            </AlertDescription>
          </Alert>
        ) : historyQuery.isLoading ? (
          <Skeleton className="h-12 w-full rounded-md" />
        ) : (
          <>
            {history && (
              <p className="text-xs text-muted-foreground">
                {t("history.cap", { used: history.cap_used, limit: history.cap_limit })}
                {/* Without the reset date "12 of 60" reads as the team's whole
                    lifetime, which is exactly what it stops being once an
                    organizer forgives the count. */}
                {history.cap_reset_at && (
                  <span className="ml-2">
                    {t("history.capReset", {
                      date: format.dateTime(new Date(history.cap_reset_at), EXPIRY_STAMP)
                    })}
                  </span>
                )}
              </p>
            )}
            {history?.items.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("history.empty")}</p>
            ) : (
              <ul className="space-y-1">
                {history?.items.map((entry) => {
                  const known = HISTORY_STATES.find((candidate) => candidate === entry.state);
                  return (
                    <li key={entry.id} className="flex flex-wrap items-center gap-2 text-xs">
                      <StatusPill tone={inviteTone(entry.state)}>
                        {known ? t(`history.state.${known}`) : entry.state}
                      </StatusPill>
                      {/* The slot is a role, and a role is a glyph here as
                          everywhere else in this feature: spelled out, "Damage"
                          and "Support" doubled the width of every ledger row.
                          `RosterSlotGlyph` still announces the role name. */}
                      <RosterSlotGlyph code={entry.slot_code} size={14} />
                      <span className="text-muted-foreground">
                        {entry.target_battle_tag
                          ? t("invite.targetLabel", { name: entry.target_battle_tag })
                          : t("invite.linkLabel")}
                      </span>
                      {entry.is_substitute && (
                        <RosterMark
                          icon={LifeBuoy}
                          label={t("member.substitute")}
                          className="text-muted-foreground"
                        />
                      )}
                      {entry.invited_at && (
                        <span className="text-muted-foreground">
                          {t("history.issued", {
                            date: format.dateTime(new Date(entry.invited_at), EXPIRY_STAMP)
                          })}
                        </span>
                      )}
                      {entry.answered_at && (
                        <span className="text-muted-foreground">
                          {t("history.answered", {
                            date: format.dateTime(new Date(entry.answered_at), EXPIRY_STAMP)
                          })}
                        </span>
                      )}
                      {/* Same `revoked` state, materially different event: staff
                          pulled the offer, the captain did not. */}
                      {entry.revoked_by_organizer && (
                        <span className="text-muted-foreground">{t("history.byOrganizer")}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * What the screen's single `ConfirmDialog` is currently asking.
 *
 * One mount with a swapped intent, not four near-identical `AlertDialog`s whose
 * only difference was their strings. `export` carries the teams it named back
 * to the organizer (and the table's `clear`, so a confirmed export drops the
 * selection it consumed); `reject` carries the team whose captain will read the
 * reason.
 */
type PendingConfirm =
  | { kind: "reject"; team: RegistrationTeam }
  | { kind: "unlock"; team: RegistrationTeam }
  | { kind: "resetCap"; team: RegistrationTeam }
  | { kind: "export"; teams: RegistrationTeam[]; clear?: () => void };

export function RegistrationTeamsBrowser({
  tournamentId,
  workspaceId
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
}>) {
  const t = useTranslations("registrationTeams");
  // Backend messages are English; every rejection here carries a machine code
  // and MUST go through the translator (§12.2).
  const tErr = useTranslations("registrationTeams.errors");
  const tSlot = useTranslations("rosterShape.slotCodes");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  // `id` (the inspector) is navigation, not narrowing: it must not drop `page`
  // the way a filter change does.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });

  const reasonId = useId();
  const placeFieldId = useId();
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectValidation, setRejectValidation] = useState<string | null>(null);
  const [withdrawMembers, setWithdrawMembers] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [placeTarget, setPlaceTarget] = useState<RegistrationTeam | null>(null);
  const [placeRegistrationId, setPlaceRegistrationId] = useState<number | null>(null);
  const [placeBattleTag, setPlaceBattleTag] = useState("");
  const [placeSearch, setPlaceSearch] = useState("");
  const [placeOpen, setPlaceOpen] = useState(false);
  const [placeSlot, setPlaceSlot] = useState<string>(ROSTER_SLOT_CODES[0]);
  const [placeSubstitute, setPlaceSubstitute] = useState(false);
  const [renameTarget, setRenameTarget] = useState<RegistrationTeam | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});
  const [nameDraft, setNameDraft] = useState<Record<number, string>>({});
  const [exportResult, setExportResult] = useState<RegistrationTeamExportResult | null>(null);

  const canManageTeams = canAccessPermission("team.update", workspaceId);
  const canExport = canAccessPermission("team.create", workspaceId);

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationTeamsAdmin(
      workspaceId,
      tournamentId,
      true
    ),
    queryFn: () => registrationTeamService.listAdmin(tournamentId, { includeTerminal: true })
  });

  /**
   * Who the organizer may place: this tournament's registrants on no team.
   *
   * The same list the captain's invite picker reads, and the reason the place
   * dialog now asks for a PLAYER instead of the registration id it used to
   * demand — that field could only be filled by someone reading the database,
   * and a typo in it named a different person's registration.
   */
  const freeAgentsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
    queryFn: () => registrationTeamService.listFreeAgents(tournamentId),
    enabled: placeTarget != null
  });

  /** Both admin variants plus the public roster: a reject or an export changes
   *  every one of them, and the two admin flags are separate cache entries. */
  const invalidateTeams = () => {
    setActionError(null);
    for (const flag of [false, true]) {
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationTeamsAdmin(workspaceId, tournamentId, flag)
      });
    }
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId)
    });
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId)
    });
  };

  const reportError = (error: unknown) =>
    setActionError(translateRegistrationTeamError(tErr, error, t("admin.actionFailed")));

  const rejectMutation = useMutation({
    mutationFn: (input: { teamId: number; withdrawMembers: boolean; reason: string }) =>
      registrationTeamService.reject(tournamentId, input.teamId, {
        withdrawMembers: input.withdrawMembers,
        reason: input.reason
      }),
    onSuccess: () => {
      invalidateTeams();
      setConfirm(null);
      notify.success(t("admin.rejectSuccess"));
    },
    onError: reportError
  });

  const exportMutation = useMutation({
    mutationFn: (teamIds: number[]) => registrationTeamService.exportRegistered(tournamentId, teamIds),
    onSuccess: (result) => {
      invalidateTeams();
      // The export writes `tournament.team` rows, which the bracket and the
      // public pages read.
      invalidateTournamentWorkspace(queryClient, tournamentId, workspaceId);

      setExportResult(result);
      setConfirm(null);
      const names = result.skipped.map((item) => item.name).join(", ");
      const description = names ? t("admin.exportSkipped", { names }) : undefined;

      if (result.imported_teams === 0) {
        notify.info(t("admin.exportNothing"), { description });
        return;
      }
      notify.success(t("admin.exportSuccess", { count: result.imported_teams }), { description });
    },
    onError: reportError
  });

  /** A withdrawn invite leaves the live chips AND lands in the ledger as
   *  `revoked_by_organizer`; a cap reset moves the ledger's floor. Both reads go. */
  const invalidateTeamInvites = (teamId: number) => {
    invalidateTeams();
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, teamId)
    });
  };

  const revokeInviteMutation = useMutation({
    mutationFn: (input: { teamId: number; inviteId: number }) =>
      registrationTeamService.revokeInviteAdmin(tournamentId, input.inviteId),
    onSuccess: (_result, input) => {
      invalidateTeamInvites(input.teamId);
      notify.success(t("admin.revokeInviteSuccess"));
    },
    onError: reportError
  });

  /**
   * The escape hatch for the total invite cap, which counts every invite the
   * team ever created — so an invite/revoke cycle burns the ceiling on invites
   * nobody can see any more, and the refusal it produces used to name an
   * organizer intervention that no endpoint provided. This is that intervention.
   */
  const resetCapMutation = useMutation({
    mutationFn: (team: RegistrationTeam) =>
      registrationTeamService.resetInviteCap(tournamentId, team.id),
    onSuccess: (_result, team) => {
      invalidateTeamInvites(team.id);
      setConfirm(null);
      notify.success(t("admin.resetCapSuccess", { team: team.name }));
    },
    onError: reportError
  });

  const unlockMutation = useMutation({
    mutationFn: (team: RegistrationTeam) =>
      registrationTeamService.unlockRoster(tournamentId, team.id),
    onSuccess: () => {
      invalidateTeams();
      setConfirm(null);
      notify.success(t("admin.unlockSuccess"));
    },
    onError: reportError
  });

  const admissionMutation = useMutation({
    mutationFn: (input: { teamId: number; admission: "pending" | "accepted" | "waitlisted" }) =>
      registrationTeamService.setAdmission(tournamentId, input.teamId, input.admission),
    onSuccess: () => {
      invalidateTeams();
      notify.success(t("admin.admissionSuccess"));
    },
    onError: reportError
  });

  const notesMutation = useMutation({
    mutationFn: (input: { teamId: number; notes: string | null }) =>
      registrationTeamService.setNotes(tournamentId, input.teamId, input.notes),
    onSuccess: () => {
      invalidateTeams();
      notify.success(t("admin.notesSuccess"));
    },
    onError: reportError
  });

  const placeAdminMutation = useMutation({
    mutationFn: (input: { teamId: number; registrationId: number; slot_code: string; is_substitute: boolean }) =>
      registrationTeamService.placeMemberAdmin(
        tournamentId,
        input.teamId,
        input.registrationId,
        { slot_code: input.slot_code, is_substitute: input.is_substitute }
      ),
    onSuccess: () => {
      invalidateTeams();
      // The placed player is not a free agent any more.
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId)
      });
      setPlaceTarget(null);
      notify.success(t("admin.placeSuccess"));
    },
    onError: reportError
  });

  const renameAdminMutation = useMutation({
    mutationFn: (input: { teamId: number; name: string }) =>
      registrationTeamService.renameAdmin(tournamentId, input.teamId, input.name),
    onSuccess: (_result, input) => {
      invalidateTeams();
      setRenameTarget(null);
      setNameDraft((current) => {
        const next = { ...current };
        delete next[input.teamId];
        return next;
      });
      notify.success(t("rename.success"));
    },
    onError: reportError
  });

  const attachAdminMutation = useMutation({
    mutationFn: (input: { teamId: number; battle_tag: string; slot_code: string; is_substitute: boolean }) =>
      registrationTeamService.attachMemberAdmin(tournamentId, input.teamId, {
        battle_tag: input.battle_tag,
        slot_code: input.slot_code,
        is_substitute: input.is_substitute
      }),
    onSuccess: () => {
      invalidateTeams();
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId)
      });
      setPlaceTarget(null);
      notify.success(t("admin.placeSuccess"));
    },
    onError: reportError
  });

  const teams = teamsQuery.data?.items ?? [];
  const unassignedPlayers = teamsQuery.data?.unassigned_players ?? 0;
  const isExportEligible = (team: RegistrationTeam) =>
    team.status === "complete" && team.is_complete && team.admission !== "waitlisted" &&
    !team.eligibility_issues?.some((issue) => issue.blocking);

  const filterDefs: FilterDef[] = useMemo(
    () => [
      {
        key: "state",
        label: t("admin.filterStatus"),
        kind: "single",
        options: (["forming", "complete", "exported", "terminal"] as const).map((value) => ({
          value,
          label: t(`admin.filters.${value}`)
        }))
      },
      {
        key: "admission",
        label: t("admin.admission"),
        kind: "single",
        options: (["pending", "accepted", "waitlisted"] as const).map((value) => ({
          value,
          label: t(`admission.${value}`)
        }))
      }
    ],
    [t]
  );
  const filters = useAdminFilters(filterDefs);
  const stateFilter = String(filters.values.state ?? "");
  const admissionFilter = String(filters.values.admission ?? "");

  // One read serves every chip: a tournament's registered teams are a few dozen
  // rows, so narrowing is local and a chip costs no request.
  const visibleTeams = useMemo(
    () =>
      teams.filter((team) => {
        if (stateFilter) {
          const status = getRegistrationTeamStatus(team);
          const matches =
            stateFilter === "terminal"
              ? status === "rejected" || status === "disbanded"
              : status === stateFilter;
          if (!matches) return false;
        }
        if (admissionFilter && (team.admission ?? "pending") !== admissionFilter) return false;
        return true;
      }),
    [teams, stateFilter, admissionFilter]
  );

  const openId = searchParams?.get("id") ?? null;
  const selectedTeam = openId
    ? (teams.find((team) => String(team.id) === openId) ?? null)
    : null;
  const selectedIndex = selectedTeam
    ? visibleTeams.findIndex((team) => team.id === selectedTeam.id)
    : -1;

  const busy = rejectMutation.isPending || exportMutation.isPending || revokeInviteMutation.isPending ||
    resetCapMutation.isPending || unlockMutation.isPending || admissionMutation.isPending ||
    notesMutation.isPending || placeAdminMutation.isPending || renameAdminMutation.isPending ||
    attachAdminMutation.isPending;
  const inlineError = actionError ? (
    <Alert variant="destructive" role="alert"><AlertDescription>{actionError}</AlertDescription></Alert>
  ) : null;

  const columns = useMemo<ColumnDef<RegistrationTeam>[]>(() => {
    const rowActions = (team: RegistrationTeam): KebabAction[] => {
      const live = team.status === "forming" || team.status === "complete";
      const editable = canManageTeams && team.exported_team_id == null && live;
      return [
        {
          label: t("rename.save"),
          icon: Pencil,
          hidden: !editable,
          onSelect: () => {
            setActionError(null);
            setRenameValue(team.name);
            setRenameTarget(team);
          }
        },
        {
          label: t("admin.place"),
          icon: UserPlus,
          hidden: !editable,
          onSelect: () => {
            setActionError(null);
            setPlaceRegistrationId(null);
            setPlaceSearch("");
            setPlaceSlot(ROSTER_SLOT_CODES[0]);
            setPlaceSubstitute(false);
            setPlaceBattleTag("");
            setPlaceTarget(team);
          }
        },
        {
          label: t("admin.unlock"),
          icon: Unlock,
          hidden: !editable || !team.roster_locked_at,
          onSelect: () => {
            setActionError(null);
            setConfirm({ kind: "unlock", team });
          }
        },
        {
          label: t("admin.resetCap"),
          icon: RotateCcw,
          hidden: !editable,
          onSelect: () => {
            setActionError(null);
            setConfirm({ kind: "resetCap", team });
          }
        },
        {
          label: t("admin.reExport"),
          icon: FolderInput,
          hidden: !canExport || team.exported_team_id == null || !isExportEligible(team),
          onSelect: () => {
            setActionError(null);
            setConfirm({ kind: "export", teams: [team] });
          }
        },
        {
          label: t("admin.reject"),
          icon: Ban,
          destructive: true,
          hidden: !editable,
          onSelect: () => {
            setActionError(null);
            setRejectValidation(null);
            setWithdrawMembers(false);
            setRejectReason("");
            setConfirm({ kind: "reject", team });
          }
        }
      ];
    };

    return [
      {
        id: "name",
        accessorFn: (team) => team.name,
        header: t("admin.columns.team"),
        cell: ({ row }) => (
          <div className="min-w-0 space-y-0.5">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="break-words font-medium">{row.original.name}</span>
              {row.original.roster_locked_at && (
                <Badge variant="outline">{t("lock.locked")}</Badge>
              )}
            </div>
            {row.original.rejection_reason && (
              <p className="break-words text-caption text-danger">
                {row.original.rejection_reason}
              </p>
            )}
          </div>
        ),
        meta: adminColumnMeta<RegistrationTeam>({
          mandatory: true,
          className: "min-w-[11rem]",
          // The two things an organizer knows a team by.
          searchValue: (team) => {
            const captain = captainOf(team);
            return `${team.name} ${captain ? memberName(captain) : ""} ${captain?.battle_tag ?? ""}`;
          }
        })
      },
      {
        id: "state",
        accessorFn: (team) => getRegistrationTeamStatus(team),
        header: t("admin.columns.state"),
        cell: ({ row }) => {
          const status = getRegistrationTeamStatus(row.original);
          return (
            <StatusPill tone={TEAM_STATUS_TONE[status] ?? "neutral"}>
              {t(`status.${status}`)}
            </StatusPill>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "admission",
        accessorFn: (team) => team.admission ?? "pending",
        header: t("admin.columns.admission"),
        cell: ({ row }) => {
          const admission = row.original.admission ?? "pending";
          return (
            <StatusPill tone={ADMISSION_TONE[admission] ?? "neutral"}>
              {t(`admission.${admission}`)}
            </StatusPill>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "captain",
        accessorFn: (team) => {
          const captain = captainOf(team);
          return captain ? memberName(captain) : "";
        },
        header: t("admin.columns.captain"),
        cell: ({ row }) => {
          const captain = captainOf(row.original);
          if (!captain) return <span className="text-muted-foreground">—</span>;
          const name = memberName(captain);
          return (
            <div className="min-w-0">
              <p className="break-words">{name}</p>
              {captain.battle_tag && captain.battle_tag !== name ? (
                <p className="break-words text-caption text-muted-foreground">
                  {captain.battle_tag}
                </p>
              ) : null}
            </div>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "roster",
        accessorFn: (team) => rosterCounts(team).starters,
        header: t("admin.columns.roster"),
        cell: ({ row }) => {
          const { starters, required } = rosterCounts(row.original);
          return (
            <span className="text-caption text-muted-foreground">
              {t("admin.rosterSummary", {
                starters,
                required,
                bench: row.original.substitutes_used,
                maxBench: row.original.max_substitutes
              })}
            </span>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core", className: "min-w-[9rem]" })
      },
      {
        // The reason the screen exists, so it is a column and not a badge.
        id: "shortfall",
        accessorFn: (team) => Object.keys(team.open_slots).length,
        header: t("admin.columns.shortfall"),
        cell: ({ row }) => {
          const team = row.original;
          const issues = team.eligibility_issues?.length ?? 0;
          const short = team.status === "forming" && team.exported_team_id == null;
          if (!short && issues === 0) return <span className="text-muted-foreground">—</span>;
          return (
            <div className="space-y-0.5 text-caption text-warning">
              {short && <p>{t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}</p>}
              {issues > 0 && <p>{t("admin.problemCount", { count: issues })}</p>}
            </div>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core", className: "min-w-[10rem]" })
      },
      createKebabColumn<RegistrationTeam>(rowActions, { rowLabel: (team) => team.name })
    ];
  }, [canExport, canManageTeams, t, tSlot]);

  /**
   * The strings — and, for a rejection, the fields — of whichever confirmation
   * is open. Derived rather than stored: every branch reads state this render
   * already has, and a second copy in state is what drifts.
   */
  let confirmIntent: ConfirmIntent;
  if (confirm?.kind === "export") {
    const label = confirm.teams.some((team) => team.exported_team_id != null)
      ? t("admin.reExport")
      : t("admin.exportSelected");
    confirmIntent = {
      title: label,
      confirmLabel: label,
      tone: "warning",
      description: (
        <div className="space-y-2">
          <p>{t("admin.exportConfirmHint")}</p>
          <ul className="max-h-48 list-inside list-disc overflow-y-auto">
            {confirm.teams.map((team) => (
              <li key={team.id}>{team.name}</li>
            ))}
          </ul>
          {inlineError}
        </div>
      )
    };
  } else if (confirm?.kind === "unlock") {
    confirmIntent = {
      title: `${t("admin.unlock")} — ${confirm.team.name}`,
      confirmLabel: t("admin.unlock"),
      tone: "warning",
      description: inlineError
    };
  } else if (confirm?.kind === "resetCap") {
    confirmIntent = {
      title: t("admin.resetCapConfirm", { team: confirm.team.name }),
      confirmLabel: t("admin.resetCap"),
      tone: "warning",
      description: inlineError
    };
  } else {
    confirmIntent = {
      title: t("admin.rejectConfirm", { team: confirm?.kind === "reject" ? confirm.team.name : "" }),
      // Never one neutral "Confirm": the button says which of the two
      // consequences below it is about to apply.
      confirmLabel: withdrawMembers ? t("admin.rejectAndWithdraw") : t("admin.rejectKeepPlayers"),
      tone: "danger",
      description: (
        <div className="space-y-3">
          <p>{t("admin.rejectConsequences")}</p>
          {inlineError}
          <fieldset disabled={rejectMutation.isPending}>
            <legend className="mb-2 text-sm font-medium">{t("admin.rejectConsequence")}</legend>
            <RadioGroup
              value={withdrawMembers ? "withdraw" : "preserve"}
              onValueChange={(value) => setWithdrawMembers(value === "withdraw")}
            >
              <Label className="flex items-start gap-2 text-sm font-normal">
                <RadioGroupItem value="preserve" className="mt-0.5" />
                {t("admin.rejectPreserve")}
              </Label>
              <Label className="flex items-start gap-2 text-sm font-normal">
                <RadioGroupItem value="withdraw" className="mt-0.5" />
                {t("admin.rejectWithdraw")}
              </Label>
            </RadioGroup>
          </fieldset>
          <Label className="grid gap-1.5 text-sm">
            {t("admin.rejectReason")}
            <Textarea
              id={reasonId}
              required
              maxLength={1000}
              disabled={rejectMutation.isPending}
              aria-invalid={!!rejectValidation}
              aria-describedby={rejectValidation ? `${reasonId}-error` : undefined}
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              rows={2}
            />
          </Label>
          {rejectValidation && (
            <p id={`${reasonId}-error`} role="alert" className="text-sm text-danger">
              {rejectValidation}
            </p>
          )}
        </div>
      )
    };
  }

  const selectedAgent = freeAgentsQuery.data?.items.find(
    (agent) => agent.registration_id === placeRegistrationId
  );

  return (
    <>
      <div
        className={cn(
          "grid min-w-0 items-start gap-4",
          selectedTeam && "lg:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]"
        )}
      >
        <div className="flex min-h-0 min-w-0 flex-col gap-3">
          {inlineError}
          {/* The export materializes registered TEAMS. A player on no team is
              invisible to it, and on a team-registration tournament neither the
              balancer nor the draft runs either — so they silently never become
              a tournament.player. Before pressing export is the only moment this
              is still cheap to fix, which is why the warning sits above the
              table rather than in the toast. */}
          {unassignedPlayers > 0 && (
            <Alert>
              <AlertDescription>
                {t("admin.unassigned", { count: unassignedPlayers })}
              </AlertDescription>
            </Alert>
          )}

          {exportResult && (
            <Alert role="status">
              <AlertDescription className="space-y-2">
                <p>{t("admin.exportResult", { imported: exportResult.imported_teams, removed: exportResult.removed_teams, players: exportResult.created_players, skipped: exportResult.skipped.length })}</p>
                {exportResult.skipped.length > 0 && (
                  <ul className="list-inside list-disc">
                    {exportResult.skipped.map((item) => {
                      const code = EXPORT_SKIP_CODES.find((known) => known === item.code);
                      return <li key={item.team_id}>{item.name}: {code ? t(`admin.skipReason.${code}`) : t("admin.actionFailed")}</li>;
                    })}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}

          {teamsQuery.isError ? (
            <Alert variant="destructive" role="alert">
              <AlertDescription>
                {translateRegistrationTeamError(tErr, teamsQuery.error, t("admin.loadFailed"))}
                <Button type="button" variant="outline" size="sm" className="ml-2" disabled={teamsQuery.isFetching} onClick={() => void teamsQuery.refetch()}>{t("admin.retry")}</Button>
              </AlertDescription>
            </Alert>
          ) : (
            <AdminDataTable<RegistrationTeam>
              rows={visibleTeams}
              isLoading={teamsQuery.isFetching}
              columns={columns}
              getRowId={(team) => String(team.id)}
              filterKey={filters.filterKey}
              initialPageSize={25}
              paging="infinite"
              rowUnit="teams"
              cellAlign="top"
              searchPlaceholder={t("admin.search")}
              emptyMessage={t("list.empty")}
              columnsStorageKey="registration-teams-table-columns"
              inspectorId={openId}
              onRowClick={(row) => {
                setActionError(null);
                setParams({ id: String(row.original.id) });
              }}
              // Only a roster the server would actually materialize can be
              // picked: selecting one it will skip is an export that silently
              // did nothing.
              enableRowSelection={
                canExport
                  ? (row) =>
                      row.original.exported_team_id == null && isExportEligible(row.original)
                  : undefined
              }
              bulkActions={
                canExport
                  ? (selected, clear) => (
                      <BulkBar count={selected.length} unit="teams" onClear={clear}>
                        <Button
                          type="button"
                          size="sm"
                          disabled={busy || teamsQuery.isFetching}
                          onClick={() => {
                            setActionError(null);
                            setConfirm({ kind: "export", teams: selected, clear });
                          }}
                        >
                          {exportMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                          ) : (
                            <FolderInput className="mr-2 h-4 w-4" aria-hidden />
                          )}
                          {t("admin.exportSelected")}
                        </Button>
                      </BulkBar>
                    )
                  : undefined
              }
              toolbar={<AdminFilterBar defs={filterDefs} filters={filters} />}
              actions={
                <span
                  className="shrink-0 text-xs tabular-nums text-muted-foreground"
                  title={t("list.count", { count: teamsQuery.data?.total ?? 0 })}
                >
                  {teamsQuery.data?.total ?? 0}
                </span>
              }
            />
          )}
        </div>

        <AdminInspector
          openId={selectedTeam ? openId : null}
          onClose={() => setParams({ id: null })}
          title={selectedTeam?.name ?? ""}
          subtitle={selectedTeam ? t(`status.${getRegistrationTeamStatus(selectedTeam)}`) : undefined}
          onPrev={
            selectedIndex > 0
              ? () => setParams({ id: String(visibleTeams[selectedIndex - 1].id) })
              : undefined
          }
          onNext={
            selectedIndex >= 0 && selectedIndex < visibleTeams.length - 1
              ? () => setParams({ id: String(visibleTeams[selectedIndex + 1].id) })
              : undefined
          }
        >
          {selectedTeam ? (
            <div className="space-y-4">
              {inlineError}
              {selectedTeam.rejection_reason && (
                <Alert variant="destructive">
                  <AlertDescription>
                    {t("admin.rejectionReason", { reason: selectedTeam.rejection_reason })}
                  </AlertDescription>
                </Alert>
              )}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusPill tone={ADMISSION_TONE[selectedTeam.admission ?? "pending"] ?? "neutral"}>
                  {t(`admission.${selectedTeam.admission ?? "pending"}`)}
                </StatusPill>
                {selectedTeam.roster_locked_at && (
                  <Badge variant="outline">{t("lock.locked")}</Badge>
                )}
                {selectedTeam.subscription_covered && (
                  <Badge variant="outline">{t("cover.covered")}</Badge>
                )}
                {typeof selectedTeam.checked_in_count === "number" && (selectedTeam.check_in_total ?? 0) > 0 && (
                  <span className="text-caption text-muted-foreground">
                    {t("checkIn.counts", {
                      done: selectedTeam.checked_in_count,
                      total: selectedTeam.check_in_total ?? 0
                    })}
                  </span>
                )}
                {selectedTeam.exported_team_id != null && (
                  <Badge variant="outline">{t("admin.inTournament")}</Badge>
                )}
                {/* The whole point of the screen: what is still missing. A full
                    roster already says so in its status pill, so only the
                    shortfall gets words of its own. */}
                {selectedTeam.status === "forming" && selectedTeam.exported_team_id == null && (
                  <span className="text-caption font-medium text-warning">
                    {t("list.shortfall", { slots: formatShortfall(selectedTeam.open_slots, tSlot) })}
                  </span>
                )}
              </div>

              {/* Roster and open invites in one wrapping strip: they fill the
                  same slots, and the dashed chip is what says "offered, not
                  taken". Two separate lists left one of them empty on most
                  teams — and "No open invites." was a whole line spent on the
                  ordinary case. */}
              {(selectedTeam.members.length > 0 || selectedTeam.invites.length > 0) && (
                <ul className="flex flex-wrap items-center gap-1.5">
                  {selectedTeam.members.map((member) => (
                    <li
                      key={member.registration_id}
                      className="flex items-center gap-1.5 rounded-md border border-border px-1.5 py-0.5 text-caption"
                    >
                      <RosterSlotGlyph code={member.slot_code} size={14} />
                      <span className="font-medium">{memberName(member)}</span>
                      {member.is_captain && (
                        <RosterMark
                          icon={Crown}
                          label={t("member.captain")}
                          className="text-warning"
                        />
                      )}
                      {member.is_manager && !member.is_captain && (
                        <span className="text-muted-foreground">{t("member.manager")}</span>
                      )}
                      {member.is_substitute && (
                        <RosterMark
                          icon={LifeBuoy}
                          label={t("member.substitute")}
                          className="text-muted-foreground"
                        />
                      )}
                    </li>
                  ))}
                  {selectedTeam.invites.map((invite) => (
                    <li
                      key={invite.id}
                      className="flex items-center gap-1.5 rounded-md border border-dashed border-border px-1.5 py-0.5 text-caption"
                    >
                      <StatusPill tone={inviteTone(invite.state)}>
                        {t(`inviteState.${invite.state}`)}
                      </StatusPill>
                      <RosterSlotGlyph code={invite.slot_code} size={14} />
                      <span className="text-muted-foreground">
                        {invite.target_battle_tag ?? t("invite.linkLabel")}
                      </span>
                      {invite.is_substitute && (
                        <RosterMark
                          icon={LifeBuoy}
                          label={t("member.substitute")}
                          className="text-muted-foreground"
                        />
                      )}
                      {invite.expires_at && (
                        <span className="text-muted-foreground">
                          {t("invite.expiresAt", {
                            date: format.dateTime(new Date(invite.expires_at), EXPIRY_STAMP)
                          })}
                        </span>
                      )}
                      {/* An organizer reaching into someone else's roster. Its
                          own label and the danger tone keep it from reading like
                          the captain's own "Revoke" — the two are the same
                          effect but not the same act, and the ledger records
                          which one happened. */}
                      {canManageTeams && !selectedTeam.roster_locked_at && selectedTeam.exported_team_id == null && (selectedTeam.status === "forming" || selectedTeam.status === "complete") && isLiveInvite(invite) && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t("admin.revokeInvite")}
                          title={t("admin.revokeInvite")}
                          className="size-6 text-danger [&_svg]:size-3.5"
                          disabled={busy || teamsQuery.isFetching}
                          onClick={() =>
                            revokeInviteMutation.mutate({
                              teamId: selectedTeam.id,
                              inviteId: invite.id
                            })
                          }
                        >
                          <X aria-hidden />
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {canManageTeams && selectedTeam.exported_team_id == null && (selectedTeam.status === "forming" || selectedTeam.status === "complete") && (
                <div className="flex flex-wrap items-center gap-2">
                  <Label
                    className="text-caption text-muted-foreground"
                    htmlFor={`admission-${selectedTeam.id}`}
                  >
                    {t("admin.admission")}
                  </Label>
                  <Select
                    value={selectedTeam.admission ?? "pending"}
                    disabled={busy || teamsQuery.isFetching}
                    onValueChange={(value) =>
                      admissionMutation.mutate({
                        teamId: selectedTeam.id,
                        admission: value as "pending" | "accepted" | "waitlisted"
                      })
                    }
                  >
                    <SelectTrigger id={`admission-${selectedTeam.id}`} className="h-8 w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(["pending", "accepted", "waitlisted"] as const).map((value) => (
                        <SelectItem key={value} value={value}>
                          {t(`admission.${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {canManageTeams && selectedTeam.exported_team_id == null && (selectedTeam.status === "forming" || selectedTeam.status === "complete") && (
                <div className="grid gap-1">
                  <Label
                    htmlFor={`name-${selectedTeam.id}`}
                    className="text-caption text-muted-foreground"
                  >
                    {t("create.nameLabel")}
                  </Label>
                  <Input
                    id={`name-${selectedTeam.id}`}
                    value={nameDraft[selectedTeam.id] ?? selectedTeam.name}
                    disabled={busy || teamsQuery.isFetching}
                    onChange={(event) =>
                      setNameDraft((current) => ({
                        ...current,
                        [selectedTeam.id]: event.target.value
                      }))
                    }
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-fit"
                    disabled={
                      busy ||
                      teamsQuery.isFetching ||
                      !(nameDraft[selectedTeam.id] ?? selectedTeam.name).trim() ||
                      (nameDraft[selectedTeam.id] ?? selectedTeam.name).trim() === selectedTeam.name
                    }
                    onClick={() =>
                      renameAdminMutation.mutate({
                        teamId: selectedTeam.id,
                        name: (nameDraft[selectedTeam.id] ?? selectedTeam.name).trim()
                      })
                    }
                  >
                    {t("rename.save")}
                  </Button>
                </div>
              )}
              {canManageTeams && (
                <div className="grid gap-1">
                  <Label
                    htmlFor={`notes-${selectedTeam.id}`}
                    className="text-caption text-muted-foreground"
                  >
                    {t("admin.notes")}
                  </Label>
                  <Textarea
                    id={`notes-${selectedTeam.id}`}
                    rows={2}
                    value={notesDraft[selectedTeam.id] ?? selectedTeam.organizer_notes ?? ""}
                    onChange={(event) =>
                      setNotesDraft((current) => ({
                        ...current,
                        [selectedTeam.id]: event.target.value
                      }))
                    }
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-fit"
                    disabled={busy || teamsQuery.isFetching}
                    onClick={() =>
                      notesMutation.mutate({
                        teamId: selectedTeam.id,
                        notes:
                          (notesDraft[selectedTeam.id] ?? selectedTeam.organizer_notes ?? "").trim() ||
                          null
                      })
                    }
                  >
                    {t("admin.notesSave")}
                  </Button>
                </div>
              )}
              {(selectedTeam.eligibility_issues?.length ?? 0) > 0 && (
                <ul className="text-caption text-warning">
                  <li className="font-medium">{t("eligibility.title")}</li>
                  {selectedTeam.eligibility_issues!.map((issue, index) => {
                    const code = REGISTRATION_TEAM_ERROR_CODES.find((known) => known === issue.code);
                    return (
                      <li key={`${issue.code}-${issue.registration_id ?? "team"}-${index}`}>
                        {code ? tErr(code) : t("admin.actionFailed")}
                      </li>
                    );
                  })}
                </ul>
              )}
              <TeamInviteHistory
                tournamentId={tournamentId}
                workspaceId={workspaceId}
                teamId={selectedTeam.id}
                meta={
                  /* Only once someone is actually on the bench: "0 of 2
                     substitutes" under every team is a constant, not news. */
                  selectedTeam.substitutes_used > 0 ? (
                    <span className="text-caption text-muted-foreground">
                      {t("list.substitutes", {
                        used: selectedTeam.substitutes_used,
                        max: selectedTeam.max_substitutes
                      })}
                    </span>
                  ) : null
                }
              />
            </div>
          ) : null}
        </AdminInspector>
      </div>

      <ConfirmDialog
        open={confirm != null}
        onOpenChange={(open) => {
          if (open || busy) return;
          setConfirm(null);
        }}
        pending={busy}
        intent={confirmIntent}
        onConfirm={() => {
          if (!confirm) return;
          setActionError(null);
          if (confirm.kind === "unlock") {
            unlockMutation.mutate(confirm.team);
            return;
          }
          if (confirm.kind === "resetCap") {
            resetCapMutation.mutate(confirm.team);
            return;
          }
          if (confirm.kind === "export") {
            const teamIds = confirm.teams.map((team) => team.id);
            if (!teamIds.length) return;
            // The teams were named back before this click; one that changed
            // underneath is a different decision than the confirmed one.
            const drifted = teamIds.some((id) => {
              const current = teams.find((team) => team.id === id);
              const confirmed = confirm.teams.find((team) => team.id === id);
              return (
                !current ||
                !isExportEligible(current) ||
                current.exported_team_id !== confirmed?.exported_team_id
              );
            });
            if (drifted) {
              setActionError(t("admin.exportSelectionChanged"));
              return;
            }
            exportMutation.mutate(teamIds, { onSuccess: confirm.clear });
            return;
          }
          const reason = rejectReason.trim();
          if (!reason) {
            setRejectValidation(t("admin.rejectReasonRequired"));
            document.getElementById(reasonId)?.focus();
            return;
          }
          setRejectValidation(null);
          rejectMutation.mutate({ teamId: confirm.team.id, withdrawMembers, reason });
        }}
      />

      <EntityFormDialog
        open={renameTarget != null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null);
        }}
        title={t("rename.save")}
        submitLabel={t("rename.save")}
        isSubmitting={renameAdminMutation.isPending}
        errorMessage={actionError ?? undefined}
        guardNavigation={false}
        onSubmit={() => {
          if (!renameTarget || !renameValue.trim()) return;
          renameAdminMutation.mutate({ teamId: renameTarget.id, name: renameValue });
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor={`${placeFieldId}-rename`}>{t("create.nameLabel")}</Label>
          <Input
            id={`${placeFieldId}-rename`}
            value={renameValue}
            disabled={renameAdminMutation.isPending}
            onChange={(event) => setRenameValue(event.target.value)}
          />
        </div>
      </EntityFormDialog>

      <EntityFormDialog
        open={placeTarget != null}
        onOpenChange={(open) => {
          if (!open) setPlaceTarget(null);
        }}
        title={`${t("admin.place")} — ${placeTarget?.name ?? ""}`}
        description={t("admin.placeHint")}
        submitLabel={t("admin.place")}
        isSubmitting={placeAdminMutation.isPending || attachAdminMutation.isPending}
        errorMessage={actionError ?? undefined}
        guardNavigation={false}
        onSubmit={() => {
          if (!placeTarget) return;
          if (placeRegistrationId != null) {
            placeAdminMutation.mutate({
              teamId: placeTarget.id,
              registrationId: placeRegistrationId,
              slot_code: placeSlot,
              is_substitute: placeSubstitute
            });
            return;
          }
          const tag = placeBattleTag.trim();
          if (!tag) return;
          attachAdminMutation.mutate({
            teamId: placeTarget.id,
            battle_tag: tag,
            slot_code: placeSlot,
            is_substitute: placeSubstitute
          });
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor={placeFieldId}>{t("invite.accountLabel")}</Label>
          <AdminCombobox
            id={placeFieldId}
            open={placeOpen}
            onOpenChange={setPlaceOpen}
            label={selectedAgent?.battle_tag ?? t("admin.placePlayerPick")}
            disabled={placeAdminMutation.isPending || attachAdminMutation.isPending}
            searchValue={placeSearch}
            onSearchValueChange={setPlaceSearch}
            searchPlaceholder={t("picker.search")}
            emptyMessage={freeAgentsQuery.isError ? t("picker.loadError") : t("picker.empty")}
            clear={
              placeRegistrationId != null
                ? {
                    label: t("picker.clear"),
                    value: "clear-selected-player",
                    onSelect: () => {
                      setPlaceRegistrationId(null);
                      setPlaceOpen(false);
                    }
                  }
                : undefined
            }
          >
            <CommandGroup>
              {(freeAgentsQuery.data?.items ?? []).map((agent) => (
                <CommandItem
                  key={agent.registration_id}
                  value={agent.battle_tag}
                  onSelect={() => {
                    setPlaceRegistrationId(agent.registration_id);
                    setPlaceOpen(false);
                  }}
                >
                  <AdminComboboxCheck selected={agent.registration_id === placeRegistrationId} />
                  <span className="truncate">{agent.battle_tag}</span>
                  {/* The roles the player registered for, as glyphs: the
                      organizer is filling one specific slot. */}
                  <span className="ml-auto flex items-center gap-1">
                    {agent.roles.map((role) => (
                      <RosterSlotGlyph key={role} code={role} size={14} />
                    ))}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </AdminCombobox>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${placeFieldId}-tag`}>{t("admin.placeBattleTag")}</Label>
          <Input
            id={`${placeFieldId}-tag`}
            value={placeBattleTag}
            disabled={placeAdminMutation.isPending || attachAdminMutation.isPending || placeRegistrationId != null}
            onChange={(event) => setPlaceBattleTag(event.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${placeFieldId}-slot`}>{t("invite.slotLabel")}</Label>
          <Select value={placeSlot} onValueChange={setPlaceSlot}>
            <SelectTrigger id={`${placeFieldId}-slot`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROSTER_SLOT_CODES.map((code) => (
                <SelectItem key={code} value={code}>
                  <span className="flex items-center gap-1.5">
                    <RosterSlotGlyph code={code} size={14} decorative />
                    {tSlot(code)}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Label className="flex items-center gap-2 text-sm font-normal">
          <Checkbox
            checked={placeSubstitute}
            onCheckedChange={(checked) => setPlaceSubstitute(checked === true)}
          />
          {t("member.substitute")}
        </Label>
      </EntityFormDialog>
    </>
  );
}
