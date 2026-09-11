"use client";

import { useId, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  ChevronDown,
  Crown,
  FolderInput,
  LifeBuoy,
  Loader2,
  MoreHorizontal,
  RotateCcw,
  Unlock,
  Users,
  X,
  type LucideIcon
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { type Tone } from "@/components/admin/tone";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { formatShortfall } from "@/lib/registration-team-shortfall";
import { REGISTRATION_TEAM_ERROR_CODES, translateRegistrationTeamError } from "@/lib/registration-team-errors";
import { ROSTER_SLOT_CODES } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";
import type {
  RegistrationTeam,
  RegistrationTeamMember
} from "@/types/registration-team.types";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { getRegistrationTeamStatus } from "@/lib/registration-team-tone";

/**
 * Organizer view of the registered teams (§8 of the team-registration design).
 *
 * The reason this card exists is the shortfall: a captain's team enters the
 * tournament only with a full roster, so "who is still incomplete" is the one
 * question an organizer asks before formation closes — it is rendered per team
 * rather than hidden behind a status badge.
 *
 * Unlike the public roster this view also shows the invites, and it is the only
 * place that can reject a team or materialize the complete ones into
 * `tournament.team` (the export). Both are server-authorized; the buttons follow
 * the same permissions so a caller is not offered an action that will 403.
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

function teamTone(status: string): Tone {
  return TEAM_STATUS_TONE[status] ?? "neutral";
}

function memberName(member: RegistrationTeamMember): string {
  return member.display_name ?? member.battle_tag ?? `#${member.registration_id}`;
}

/**
 * Captain / substitute marker.
 *
 * The glyph replaces the word: on a card whose whole job is fitting every team
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
  slotLabel,
  meta
}: Readonly<{
  tournamentId: number;
  workspaceId: number;
  teamId: number;
  slotLabel: (code: string | null) => string;
  /** Rendered on the trigger's own line — a second full-width row for one
   *  short counter is the kind of thing that made this card three screens. */
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
                      <span className="text-muted-foreground">{slotLabel(entry.slot_code)}</span>
                      <span className="text-muted-foreground">
                        {entry.target_battle_tag
                          ? t("invite.targetLabel", { name: entry.target_battle_tag })
                          : t("invite.linkLabel")}
                      </span>
                      {entry.is_substitute && (
                        <span className="text-muted-foreground">{t("member.substitute")}</span>
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

export function RegistrationTeamsCard({
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
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();

  const searchId = useId();
  const statusFilterId = useId();
  const reasonId = useId();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [exportTargets, setExportTargets] = useState<RegistrationTeam[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectValidation, setRejectValidation] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<RegistrationTeam | null>(null);
  const [resetTarget, setResetTarget] = useState<RegistrationTeam | null>(null);
  const [withdrawMembers, setWithdrawMembers] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [unlockTarget, setUnlockTarget] = useState<RegistrationTeam | null>(null);
  const [placeTarget, setPlaceTarget] = useState<RegistrationTeam | null>(null);
  const [placeRegistrationId, setPlaceRegistrationId] = useState("");
  const [placeSlot, setPlaceSlot] = useState<string>(ROSTER_SLOT_CODES[0]);
  const [placeSubstitute, setPlaceSubstitute] = useState(false);
  const [renameTarget, setRenameTarget] = useState<RegistrationTeam | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});
  const [exportResult, setExportResult] = useState<Awaited<ReturnType<typeof registrationTeamService.exportRegistered>> | null>(null);

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
      setRejectTarget(null);
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
      setExportTargets([]);
      setSelectedIds([]);
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
      setResetTarget(null);
      notify.success(t("admin.resetCapSuccess", { team: team.name }));
    },
    onError: reportError
  });

  const unlockMutation = useMutation({
    mutationFn: (team: RegistrationTeam) =>
      registrationTeamService.unlockRoster(tournamentId, team.id),
    onSuccess: () => {
      invalidateTeams();
      setUnlockTarget(null);
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
      setPlaceTarget(null);
      notify.success(t("admin.placeSuccess"));
    },
    onError: reportError
  });

  const renameAdminMutation = useMutation({
    mutationFn: (input: { teamId: number; name: string }) =>
      registrationTeamService.renameAdmin(tournamentId, input.teamId, input.name),
    onSuccess: () => {
      invalidateTeams();
      setRenameTarget(null);
      notify.success(t("rename.success"));
    },
    onError: reportError
  });

  /** Slot codes are shared vocabulary; an unknown one renders raw rather than
   *  throwing on a missing message. */
  const slotLabel = (code: string | null): string => {
    const known = ROSTER_SLOT_CODES.find((candidate) => candidate === code);
    return known ? tSlot(known) : (code ?? "—");
  };

  const teams = teamsQuery.data?.items ?? [];
  const unassignedPlayers = teamsQuery.data?.unassigned_players ?? 0;
  const selectedTeam = teams.find((team) => team.id === selectedTeamId);
  const isExportEligible = (team: RegistrationTeam) =>
    team.status === "complete" && team.is_complete && team.admission !== "waitlisted" &&
    !team.eligibility_issues?.some((issue) => issue.blocking);
  const selectedExportTeams = teams.filter((team) =>
    selectedIds.includes(team.id) && team.exported_team_id == null && isExportEligible(team)
  );
  const needle = search.trim().toLocaleLowerCase();
  const visibleTeams = teams.filter((team) => {
    const status = getRegistrationTeamStatus(team);
    const matchesStatus = statusFilter === "all" ||
      (statusFilter === "terminal" ? status === "rejected" || status === "disbanded" : status === statusFilter);
    const captain = team.members.find((member) => member.is_captain);
    return matchesStatus && (!needle || `${team.name} ${captain ? memberName(captain) : ""} ${captain?.battle_tag ?? ""}`.toLocaleLowerCase().includes(needle));
  });
  const busy = rejectMutation.isPending || exportMutation.isPending || revokeInviteMutation.isPending ||
    resetCapMutation.isPending || unlockMutation.isPending || admissionMutation.isPending ||
    notesMutation.isPending || placeAdminMutation.isPending || renameAdminMutation.isPending;
  const inlineError = actionError ? (
    <Alert variant="destructive" role="alert"><AlertDescription>{actionError}</AlertDescription></Alert>
  ) : null;

  return (
    <>
      <div className={cn("grid min-w-0 gap-4", selectedTeam && "lg:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]")}>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 pb-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Users className="size-4 text-primary" aria-hidden />
              <CardTitle>{t("admin.title")}</CardTitle>
            </div>
            <CardDescription>
              {t("list.count", { count: teamsQuery.data?.total ?? 0 })}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <span className="text-sm text-muted-foreground">
              {t("admin.selectedCount", { count: selectedExportTeams.length })}
            </span>
            {canExport && (
              <Button
                type="button"
                disabled={busy || teamsQuery.isFetching || selectedExportTeams.length === 0}
                onClick={() => {
                  setActionError(null);
                  setExportTargets(selectedExportTeams);
                }}
              >
                {exportMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <FolderInput className="mr-2 h-4 w-4" aria-hidden />
                )}
                {t("admin.exportSelected")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <Label htmlFor={searchId}>{t("admin.search")}</Label>
              <Input id={searchId} type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor={statusFilterId}>{t("admin.filterStatus")}</Label>
              <select id={statusFilterId} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                {(["all", "forming", "complete", "exported", "terminal"] as const).map((status) => (
                  <option key={status} value={status}>{t(`admin.filters.${status}`)}</option>
                ))}
              </select>
            </div>
          </div>
          {inlineError}
          {/* The export materializes registered TEAMS. A player on no team is
              invisible to it, and on a team-registration tournament neither the
              balancer nor the draft runs either — so they silently never become a
              tournament.player. Before pressing export is the only moment this is
              still cheap to fix, which is why the warning sits above the button's
              own results rather than in the toast. */}
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
          ) : teamsQuery.isLoading ? (
            <Skeleton className="h-40 w-full rounded-lg" />
          ) : teams.length === 0 ? (
            <EmptyNote icon={Users} title={t("list.empty")}>{t("admin.emptyHint")}</EmptyNote>
          ) : visibleTeams.length === 0 ? (
            <EmptyNote icon={Users} title={t("admin.noResults")}>
              <Button type="button" variant="outline" onClick={() => { setSearch(""); setStatusFilter("all"); }}>{t("admin.clearFilters")}</Button>
            </EmptyNote>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {visibleTeams.map((team) => {
                const captain = team.members.find((member) => member.is_captain);
                const status = getRegistrationTeamStatus(team);
                const starters = team.members.filter((member) => !member.is_substitute).length;
                const required = starters + Object.values(team.open_slots).reduce((sum, count) => sum + (count ?? 0), 0);
                const selectable = team.exported_team_id == null && isExportEligible(team);
                return (
                  <li key={team.id} className={cn("flex items-start gap-3 p-3", selectedTeamId === team.id && "bg-accent/30")}>
                    {canExport && <Checkbox className="mt-1" aria-label={t("admin.selectTeam", { team: team.name })} checked={selectable && selectedIds.includes(team.id)} disabled={!selectable || busy || teamsQuery.isFetching} onCheckedChange={(checked) => setSelectedIds((current) => checked === true ? [...current, team.id] : current.filter((id) => id !== team.id))} />}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="break-words font-medium">{team.name}</span>
                        <StatusPill tone={teamTone(status)}>{t(`status.${status}`)}</StatusPill>
                        {team.roster_locked_at && <Badge variant="outline">{t("lock.locked")}</Badge>}
                      </div>
                      <p className="break-words text-sm text-muted-foreground">{t("admin.captainSummary", { name: captain ? memberName(captain) : "—" })}</p>
                      <p className="text-caption text-muted-foreground">{t("admin.rosterSummary", { starters, required, bench: team.substitutes_used, maxBench: team.max_substitutes })}</p>
                      {status === "forming" && <p className="text-caption text-warning">{t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}</p>}
                      {team.admission === "waitlisted" && <p className="text-caption text-warning">{t("admission.waitlisted")}</p>}
                      {(team.eligibility_issues?.length ?? 0) > 0 && <p className="text-caption text-warning">{t("admin.problemCount", { count: team.eligibility_issues!.length })}</p>}
                      {team.rejection_reason && <p className="break-words text-caption text-danger">{team.rejection_reason}</p>}
                    </div>
                    <Button type="button" variant="outline" size="sm" aria-label={t("admin.inspectTeam", { team: team.name })} onClick={() => { setActionError(null); setSelectedTeamId(team.id); }}>{t("admin.inspect")}</Button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
      <AdminInspector openId={selectedTeam ? String(selectedTeam.id) : null} onClose={() => setSelectedTeamId(null)} title={selectedTeam?.name ?? ""}>
              {selectedTeam && [selectedTeam].map((team) => (
                <div key={team.id} className="space-y-4">
                  {inlineError}
                  {team.rejection_reason && (
                    <Alert variant="destructive"><AlertDescription>{t("admin.rejectionReason", { reason: team.rejection_reason })}</AlertDescription></Alert>
                  )}
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="truncate font-medium">{team.name}</span>
                    <StatusPill tone={teamTone(getRegistrationTeamStatus(team))}>
                      {t(`status.${getRegistrationTeamStatus(team)}`)}
                    </StatusPill>
                    <StatusPill
                      tone={
                        team.admission === "accepted"
                          ? "success"
                          : team.admission === "waitlisted"
                            ? "neutral"
                            : "warning"
                      }
                    >
                      {t(`admission.${team.admission ?? "pending"}`)}
                    </StatusPill>
                    {team.roster_locked_at && (
                      <Badge variant="outline">{t("lock.locked")}</Badge>
                    )}
                    {team.subscription_covered && (
                      <Badge variant="outline">{t("cover.covered")}</Badge>
                    )}
                    {typeof team.checked_in_count === "number" && (team.check_in_total ?? 0) > 0 && (
                      <span className="text-caption text-muted-foreground">
                        {t("checkIn.counts", {
                          done: team.checked_in_count,
                          total: team.check_in_total ?? 0
                        })}
                      </span>
                    )}
                    {team.exported_team_id != null && (
                      <Badge variant="outline">{t("admin.inTournament")}</Badge>
                    )}
                    {/* The whole point of the card: what is still missing. A full
                        roster already says so in its status pill, so only the
                        shortfall gets words of its own — the sentence that used
                        to repeat "Roster complete" under the pill was a line per
                        team saying nothing new. */}
                    {team.status === "forming" && team.exported_team_id == null && (
                      <span className="text-caption font-medium text-warning">
                        {t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}
                      </span>
                    )}
                    {canExport && team.exported_team_id != null && isExportEligible(team) && (
                      <Button type="button" variant="outline" size="sm" disabled={busy || teamsQuery.isFetching} onClick={() => { setActionError(null); setExportTargets([team]); }}>
                        {t("admin.reExport")}
                      </Button>
                    )}
                    {/* The admin's one row-actions convention (DESIGN.md): the
                        two labelled buttons cost ~260px of the row a two-column
                        grid no longer has. An action the caller may not perform
                        is absent, never disabled. */}
                    {canManageTeams && team.exported_team_id == null && (team.status === "forming" || team.status === "complete") && (
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          disabled={busy || teamsQuery.isFetching}
                          aria-label={t("admin.rowActions", { team: team.name })}
                          className="ml-auto inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <MoreHorizontal aria-hidden className="size-4" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-56">
                          <DropdownMenuItem
                            className="gap-2"
                            onSelect={() => {
                              setActionError(null);
                              setRenameValue(team.name);
                              setRenameTarget(team);
                            }}
                          >
                            {t("rename.save")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="gap-2"
                            onSelect={() => {
                              setActionError(null);
                              setPlaceRegistrationId("");
                              setPlaceSlot(ROSTER_SLOT_CODES[0]);
                              setPlaceSubstitute(false);
                              setPlaceTarget(team);
                            }}
                          >
                            {t("admin.place")}
                          </DropdownMenuItem>
                          {team.roster_locked_at && (
                            <DropdownMenuItem
                              className="gap-2"
                              onSelect={() => { setActionError(null); setUnlockTarget(team); }}
                            >
                              <Unlock aria-hidden className="size-3.5" />
                              {t("admin.unlock")}
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem
                            className="gap-2"
                            onSelect={() => { setActionError(null); setResetTarget(team); }}
                          >
                            <RotateCcw aria-hidden className="size-3.5" />
                            {t("admin.resetCap")}
                          </DropdownMenuItem>
                          {(team.status === "forming" || team.status === "complete") && (
                            <DropdownMenuItem
                              className="gap-2 text-danger focus:text-danger"
                              onSelect={() => {
                                setActionError(null);
                                setRejectValidation(null);
                                setWithdrawMembers(false);
                                setRejectReason("");
                                setRejectTarget(team);
                              }}
                            >
                              <Ban aria-hidden className="size-3.5" />
                              {t("admin.reject")}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>

                  {/* Roster and open invites in one wrapping strip: they fill the
                      same slots, and the dashed chip is what says "offered, not
                      taken". Two separate lists left one of them empty on most
                      teams — and "No open invites." was a whole line spent on
                      the ordinary case. */}
                  {(team.members.length > 0 || team.invites.length > 0) && (
                    <ul className="flex flex-wrap items-center gap-1.5">
                      {team.members.map((member) => (
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
                      {team.invites.map((invite) => (
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
                              own label and the danger tone keep it from reading
                              like the captain's own "Revoke" — the two are the
                              same effect but not the same act, and the ledger
                              records which one happened. */}
                          {canManageTeams && !team.roster_locked_at && team.exported_team_id == null && (team.status === "forming" || team.status === "complete") && invite.state === "pending" && (!invite.expires_at || new Date(invite.expires_at).getTime() > Date.now()) && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t("admin.revokeInvite")}
                              title={t("admin.revokeInvite")}
                              className="size-6 text-danger [&_svg]:size-3.5"
                              disabled={busy || teamsQuery.isFetching}
                              onClick={() =>
                                revokeInviteMutation.mutate({ teamId: team.id, inviteId: invite.id })
                              }
                            >
                              <X aria-hidden />
                            </Button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}

                  {canManageTeams && team.exported_team_id == null && (team.status === "forming" || team.status === "complete") && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Label className="text-caption text-muted-foreground" htmlFor={`admission-${team.id}`}>
                        {t("admin.admission")}
                      </Label>
                      <select
                        id={`admission-${team.id}`}
                        className="h-8 rounded-md border border-input bg-transparent px-2 text-caption"
                        value={team.admission ?? "pending"}
                        disabled={busy || teamsQuery.isFetching}
                        onChange={(event) =>
                          admissionMutation.mutate({
                            teamId: team.id,
                            admission: event.target.value as "pending" | "accepted" | "waitlisted"
                          })
                        }
                      >
                        <option value="pending">{t("admission.pending")}</option>
                        <option value="accepted">{t("admission.accepted")}</option>
                        <option value="waitlisted">{t("admission.waitlisted")}</option>
                      </select>
                    </div>
                  )}
                  {canManageTeams && (
                    <div className="grid gap-1">
                      <Label htmlFor={`notes-${team.id}`} className="text-caption text-muted-foreground">
                        {t("admin.notes")}
                      </Label>
                      <Textarea
                        id={`notes-${team.id}`}
                        rows={2}
                        value={notesDraft[team.id] ?? team.organizer_notes ?? ""}
                        onChange={(event) =>
                          setNotesDraft((current) => ({ ...current, [team.id]: event.target.value }))
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
                            teamId: team.id,
                            notes: (notesDraft[team.id] ?? team.organizer_notes ?? "").trim() || null
                          })
                        }
                      >
                        {t("admin.notesSave")}
                      </Button>
                    </div>
                  )}
                  {(team.eligibility_issues?.length ?? 0) > 0 && (
                    <ul className="text-caption text-warning">
                      <li className="font-medium">{t("eligibility.title")}</li>
                      {team.eligibility_issues!.map((issue, index) => {
                        const code = REGISTRATION_TEAM_ERROR_CODES.find((known) => known === issue.code);
                        return <li key={`${issue.code}-${issue.registration_id ?? "team"}-${index}`}>{code ? tErr(code) : t("admin.actionFailed")}</li>;
                      })}
                    </ul>
                  )}
                  <TeamInviteHistory
                    tournamentId={tournamentId}
                    workspaceId={workspaceId}
                    teamId={team.id}
                    slotLabel={slotLabel}
                    meta={
                      /* Only once someone is actually on the bench: "0 of 2
                         substitutes" under every team is a constant, not news. */
                      team.substitutes_used > 0 ? (
                        <span className="text-caption text-muted-foreground">
                          {t("list.substitutes", {
                            used: team.substitutes_used,
                            max: team.max_substitutes
                          })}
                        </span>
                      ) : null
                    }
                  />
                </div>
              ))}
      </AdminInspector>
      </div>

      <AlertDialog
        open={rejectTarget != null}
        onOpenChange={(open) => !open && !rejectMutation.isPending && setRejectTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("admin.rejectConfirm", { team: rejectTarget?.name ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t("admin.rejectConsequences")}</AlertDialogDescription>
          </AlertDialogHeader>
          {inlineError}
          <fieldset className="space-y-3" disabled={rejectMutation.isPending}>
            <legend className="mb-2 text-sm font-medium">{t("admin.rejectConsequence")}</legend>
            <Label className="flex items-start gap-2 text-sm font-normal">
              <input type="radio" name={`consequence-${reasonId}`} checked={!withdrawMembers} onChange={() => setWithdrawMembers(false)} />
              {t("admin.rejectPreserve")}
            </Label>
            <Label className="flex items-start gap-2 text-sm font-normal">
              <input type="radio" name={`consequence-${reasonId}`} checked={withdrawMembers} onChange={() => setWithdrawMembers(true)} />
              {t("admin.rejectWithdraw")}
            </Label>
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
          {rejectValidation && <p id={`${reasonId}-error`} role="alert" className="text-sm text-danger">{rejectValidation}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={rejectMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              className={buttonVariants({ variant: "destructive" })}
              disabled={rejectMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!rejectTarget) return;
                const reason = rejectReason.trim();
                if (!reason) {
                  setRejectValidation(t("admin.rejectReasonRequired"));
                  document.getElementById(reasonId)?.focus();
                  return;
                }
                setRejectValidation(null);
                setActionError(null);
                rejectMutation.mutate({
                  teamId: rejectTarget.id,
                  withdrawMembers,
                  reason
                });
              }}
            >
              {rejectMutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" aria-hidden />}
              {withdrawMembers ? t("admin.rejectAndWithdraw") : t("admin.rejectKeepPlayers")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={exportTargets.length > 0} onOpenChange={(open) => !open && !exportMutation.isPending && setExportTargets([])}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{exportTargets.some((team) => team.exported_team_id != null) ? t("admin.reExport") : t("admin.exportSelected")}</AlertDialogTitle>
            <AlertDialogDescription>{t("admin.exportConfirmHint")}</AlertDialogDescription>
          </AlertDialogHeader>
          <ul className="max-h-60 list-inside list-disc overflow-y-auto">{exportTargets.map((team) => <li key={team.id}>{team.name}</li>)}</ul>
          {inlineError}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={exportMutation.isPending}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction disabled={exportMutation.isPending || teamsQuery.isFetching} onClick={(event) => {
              event.preventDefault();
              const teamIds = exportTargets.map((team) => team.id);
              if (!teamIds.length) return;
              if (teamIds.some((id) => {
                const current = teams.find((team) => team.id === id);
                const confirmed = exportTargets.find((team) => team.id === id);
                return !current || !isExportEligible(current) || current.exported_team_id !== confirmed?.exported_team_id;
              })) {
                setActionError(t("admin.exportSelectionChanged"));
                return;
              }
              setActionError(null);
              exportMutation.mutate(teamIds);
            }}>
              {exportMutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" aria-hidden />}
              {exportTargets.some((team) => team.exported_team_id != null) ? t("admin.reExport") : t("admin.exportSelected")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={unlockTarget != null}
        onOpenChange={(open) => !open && setUnlockTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("admin.unlock")} — {unlockTarget?.name ?? ""}
            </AlertDialogTitle>
          </AlertDialogHeader>
          {inlineError}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={unlockMutation.isPending}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={unlockMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!unlockTarget) return;
                unlockMutation.mutate(unlockTarget);
              }}
            >
              {t("admin.unlock")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={renameTarget != null}
        onOpenChange={(open) => !open && setRenameTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("rename.save")}</AlertDialogTitle>
          </AlertDialogHeader>
          {inlineError}
          <Label className="grid gap-1.5">{t("rename.save")}<Input value={renameValue} disabled={renameAdminMutation.isPending} onChange={(event) => setRenameValue(event.target.value)} /></Label>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={renameAdminMutation.isPending}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={renameAdminMutation.isPending || !renameValue.trim()}
              onClick={(event) => {
                event.preventDefault();
                if (!renameTarget) return;
                renameAdminMutation.mutate({ teamId: renameTarget.id, name: renameValue });
              }}
            >
              {t("rename.save")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={placeTarget != null}
        onOpenChange={(open) => !open && setPlaceTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("admin.place")} — {placeTarget?.name ?? ""}
            </AlertDialogTitle>
          </AlertDialogHeader>
          {inlineError}
          <Label className="grid gap-1.5 text-sm">
            {t("admin.placeRegistrationId")}
            <Input
              inputMode="numeric"
              value={placeRegistrationId}
              disabled={placeAdminMutation.isPending}
              onChange={(event) => setPlaceRegistrationId(event.target.value)}
            />
          </Label>
          <Label className="grid gap-1.5 text-sm">
            {t("invite.slotLabel")}
            <select
              className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
              value={placeSlot}
              onChange={(event) => setPlaceSlot(event.target.value)}
            >
              {ROSTER_SLOT_CODES.map((code) => (
                <option key={code} value={code}>
                  {slotLabel(code)}
                </option>
              ))}
            </select>
          </Label>
          <Label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={placeSubstitute}
              onCheckedChange={(checked) => setPlaceSubstitute(checked === true)}
            />
            {t("member.substitute")}
          </Label>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={placeAdminMutation.isPending}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={placeAdminMutation.isPending || !Number.isInteger(Number(placeRegistrationId)) || Number(placeRegistrationId) <= 0}
              onClick={(event) => {
                event.preventDefault();
                if (!placeTarget) return;
                const registrationId = Number(placeRegistrationId);
                if (!Number.isInteger(registrationId) || registrationId <= 0) return;
                placeAdminMutation.mutate({
                  teamId: placeTarget.id,
                  registrationId,
                  slot_code: placeSlot,
                  is_substitute: placeSubstitute
                });
              }}
            >
              {t("admin.place")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* The admin area's existing confirmation primitive, same as the reject
          above: a forgiven count cannot be un-forgiven. */}
      <AlertDialog
        open={resetTarget != null}
        onOpenChange={(open) => !open && setResetTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("admin.resetCapConfirm", { team: resetTarget?.name ?? "" })}
            </AlertDialogTitle>
          </AlertDialogHeader>
          {inlineError}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resetCapMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={resetCapMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!resetTarget) return;
                resetCapMutation.mutate(resetTarget);
              }}
            >
              {t("admin.resetCap")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
