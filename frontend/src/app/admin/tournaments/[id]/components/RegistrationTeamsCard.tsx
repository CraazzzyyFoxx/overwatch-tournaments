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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { translateRegistrationTeamError } from "@/lib/registration-team-errors";
import { formatShortfall } from "@/lib/registration-team-shortfall";
import { ROSTER_SLOT_CODES } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";
import type {
  RegistrationTeam,
  RegistrationTeamMember,
  RegistrationTeamStatus
} from "@/types/registration-team.types";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

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
/** Every tinted status badge in the admin uses the same tone vocabulary
 *  (`@/components/admin/tone`) — the same recipe `TournamentSettingsTab` and
 *  `StageManager` already use — so `forming`/`complete` carry the same
 *  warning/success weight the public roster gives them
 *  (`RegistrationTeamsList.tsx`'s tone map) instead of the plain neutral
 *  Badge variants this card used to invent on its own. */
const STATUS_TONE: Record<RegistrationTeamStatus, Tone> = {
  forming: "warning",
  complete: "success",
  rejected: "danger",
  disbanded: "neutral"
};

const EXPIRY_STAMP = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit"
} as const;

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
        {historyQuery.isLoading ? (
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

  const terminalToggleId = useId();
  const withdrawCheckboxId = useId();
  const [includeTerminal, setIncludeTerminal] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<RegistrationTeam | null>(null);
  const [resetTarget, setResetTarget] = useState<RegistrationTeam | null>(null);
  const [withdrawMembers, setWithdrawMembers] = useState(true);
  // Kept after the toast expires: an organizer who looks away must still be able
  // to see which teams did not make it into the tournament (§12.5).
  const [skippedNames, setSkippedNames] = useState<string | null>(null);

  const canManageTeams = canAccessPermission("team.update", workspaceId);
  const canExport = canAccessPermission("team.create", workspaceId);

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationTeamsAdmin(
      workspaceId,
      tournamentId,
      includeTerminal
    ),
    queryFn: () => registrationTeamService.listAdmin(tournamentId, { includeTerminal })
  });

  /** Both admin variants plus the public roster: a reject or an export changes
   *  every one of them, and the two admin flags are separate cache entries. */
  const invalidateTeams = () => {
    for (const flag of [false, true]) {
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationTeamsAdmin(workspaceId, tournamentId, flag)
      });
    }
    void queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId)
    });
  };

  const rejectMutation = useMutation({
    mutationFn: (input: { teamId: number; withdrawMembers: boolean }) =>
      registrationTeamService.reject(tournamentId, input.teamId, {
        withdrawMembers: input.withdrawMembers
      }),
    onSuccess: () => {
      invalidateTeams();
      setRejectTarget(null);
      notify.success(t("admin.rejectSuccess"));
    },
    onError: (error) => notify.error(translateRegistrationTeamError(tErr, error))
  });

  const exportMutation = useMutation({
    // No team ids: every complete team goes.
    mutationFn: () => registrationTeamService.exportRegistered(tournamentId),
    onSuccess: (result) => {
      invalidateTeams();
      // The export writes `tournament.team` rows, which the bracket and the
      // public pages read.
      invalidateTournamentWorkspace(queryClient, tournamentId, workspaceId);

      const names = result.skipped.map((item) => item.name).join(", ");
      setSkippedNames(names || null);
      const description = names ? t("admin.exportSkipped", { names }) : undefined;

      if (result.imported_teams === 0) {
        notify.info(t("admin.exportNothing"), { description });
        return;
      }
      notify.success(t("admin.exportSuccess", { count: result.imported_teams }), { description });
    },
    onError: (error) => notify.error(translateRegistrationTeamError(tErr, error))
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
    onError: (error) => notify.error(translateRegistrationTeamError(tErr, error))
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
    onError: (error) => notify.error(translateRegistrationTeamError(tErr, error))
  });

  /** Slot codes are shared vocabulary; an unknown one renders raw rather than
   *  throwing on a missing message. */
  const slotLabel = (code: string | null): string => {
    const known = ROSTER_SLOT_CODES.find((candidate) => candidate === code);
    return known ? tSlot(known) : (code ?? "—");
  };

  const teams = teamsQuery.data?.items ?? [];
  const unassignedPlayers = teamsQuery.data?.unassigned_players ?? 0;

  return (
    <>
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
            <div className="flex shrink-0 items-center gap-2">
              <Switch
                id={terminalToggleId}
                checked={includeTerminal}
                onCheckedChange={setIncludeTerminal}
              />
              <Label htmlFor={terminalToggleId} className="cursor-pointer text-sm font-normal">
                {t("admin.includeTerminal")}
              </Label>
            </div>
            {canExport && (
              <Button
                type="button"
                disabled={exportMutation.isPending}
                onClick={() => exportMutation.mutate()}
              >
                {exportMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <FolderInput className="mr-2 h-4 w-4" aria-hidden />
                )}
                {t("admin.export")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
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

          {skippedNames && (
            <Alert variant="destructive">
              <AlertDescription>
                {t("admin.exportSkipped", { names: skippedNames })}
              </AlertDescription>
            </Alert>
          )}

          {teamsQuery.isLoading ? (
            <div className="grid gap-2 xl:grid-cols-2">
              <Skeleton className="h-20 w-full rounded-lg" />
              <Skeleton className="h-20 w-full rounded-lg" />
            </div>
          ) : teams.length === 0 ? (
            <EmptyNote icon={Users} title={t("list.empty")}>
              {t("admin.emptyHint")}
            </EmptyNote>
          ) : (
            /* Two columns from `xl`. One team is about 700px of content, so a
               full-width row per team spent half of a 1500px admin viewport on
               nothing and pushed the fifth team below the fold — on the one
               screen whose question ("who is still short?") is answered by
               seeing every team at once. */
            <div className="grid gap-2 xl:grid-cols-2">
              {teams.map((team) => (
                <div
                  key={team.id}
                  className="space-y-1.5 rounded-lg border border-border p-2.5"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="truncate font-medium">{team.name}</span>
                    <StatusPill tone={STATUS_TONE[team.status]}>
                      {t(`status.${team.status}`)}
                    </StatusPill>
                    {team.exported_team_id != null && (
                      <Badge variant="outline">{t("admin.inTournament")}</Badge>
                    )}
                    {/* The whole point of the card: what is still missing. A full
                        roster already says so in its status pill, so only the
                        shortfall gets words of its own — the sentence that used
                        to repeat "Roster complete" under the pill was a line per
                        team saying nothing new. */}
                    {!team.is_complete && (
                      <span className="text-caption font-medium text-warning">
                        {t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}
                      </span>
                    )}
                    {/* The admin's one row-actions convention (DESIGN.md): the
                        two labelled buttons cost ~260px of the row a two-column
                        grid no longer has. An action the caller may not perform
                        is absent, never disabled. */}
                    {canManageTeams && team.exported_team_id == null && (
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          aria-label={t("admin.rowActions", { team: team.name })}
                          className="ml-auto inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <MoreHorizontal aria-hidden className="size-4" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-56">
                          <DropdownMenuItem
                            className="gap-2"
                            onSelect={() => setResetTarget(team)}
                          >
                            <RotateCcw aria-hidden className="size-3.5" />
                            {t("admin.resetCap")}
                          </DropdownMenuItem>
                          {(team.status === "forming" || team.status === "complete") && (
                            <DropdownMenuItem
                              className="gap-2 text-danger focus:text-danger"
                              onSelect={() => {
                                setWithdrawMembers(true);
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
                          {canManageTeams && invite.state === "pending" && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t("admin.revokeInvite")}
                              title={t("admin.revokeInvite")}
                              className="size-6 text-danger [&_svg]:size-3.5"
                              disabled={revokeInviteMutation.isPending}
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
            </div>
          )}
        </CardContent>
      </Card>

      <AlertDialog
        open={rejectTarget != null}
        onOpenChange={(open) => !open && setRejectTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("admin.rejectConfirm", { team: rejectTarget?.name ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t("admin.rejectWithdrawHint")}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex items-start gap-2">
            <Checkbox
              id={withdrawCheckboxId}
              checked={withdrawMembers}
              onCheckedChange={(checked) => setWithdrawMembers(checked === true)}
            />
            <Label
              htmlFor={withdrawCheckboxId}
              className="cursor-pointer text-sm font-normal leading-snug"
            >
              {t("admin.rejectWithdraw")}
            </Label>
          </div>
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
                rejectMutation.mutate({ teamId: rejectTarget.id, withdrawMembers });
              }}
            >
              {t("admin.reject")}
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
