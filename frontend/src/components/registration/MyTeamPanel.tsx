"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Crown, Lock, LogOut, Trash2, UserCheck, UserMinus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import InviteHistorySection from "@/components/registration/InviteHistorySection";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { notify } from "@/lib/notify";
import { MAX_AVATAR_BYTES } from "@/lib/avatar";
import { buildInviteLink } from "@/lib/invite-link";
import {
  registrationTeamErrorCode,
  translateRegistrationTeamError,
} from "@/lib/registration-team-errors";
import { formatShortfall } from "@/lib/registration-team-shortfall";
import { getRegistrationTeamStatus, REGISTRATION_TEAM_STATUS_TONE } from "@/lib/registration-team-tone";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationTeam, RegistrationTeamMember } from "@/types/registration-team.types";

interface MyTeamPanelProps {
  workspaceId: number;
  tournamentId: number;
  team: RegistrationTeam;
  /** True when the viewer is this team's captain. Transfer, disband, lock and
   *  the manager flag stay captain-only; invite/kick/place/extend are staff. */
  isCaptain: boolean;
  viewerRegistrationId?: number;
  subscriptionScope?: "player" | "team";
  registrationOpen: boolean;
  checkInAvailable: boolean;
}

/**
 * The roster-management surface for a team the viewer belongs to.
 *
 * Captain-only actions are hidden for ordinary members, who keep exactly one:
 * leaving. A captain cannot leave — they must transfer or disband, because a
 * captain silently vanishing from a team other people already joined leaves a
 * roster nobody can edit (the server enforces this as `captain_must_transfer`).
 */
export default function MyTeamPanel({
  workspaceId,
  tournamentId,
  team,
  isCaptain,
  viewerRegistrationId,
  subscriptionScope = "player",
  registrationOpen,
  checkInAvailable,
}: Readonly<MyTeamPanelProps>) {
  const t = useTranslations("registrationTeams");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("registrationTeams.errors");
  // The same translated slot vocabulary the admin card and the public tab use, so
  // one roster never shows "DPS" in its shortfall and "Урон" on a chip.
  const tSlot = useTranslations("rosterShape.slotCodes");
  const queryClient = useQueryClient();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteMode, setInviteMode] = useState<"link" | "targeted">("link");
  const [inviteSlot, setInviteSlot] = useState<RosterSlotCode | null>(null);
  const [inviteSubstitute, setInviteSubstitute] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  /** A registration id, not an account id. Targeted mode requires a selection. */
  const [targetRegistrationId, setTargetRegistrationId] = useState<number | null>(null);
  /** Named rather than enforced by a dead submit: an unmade choice must say so. */
  const [inviteValidation, setInviteValidation] = useState<string | null>(null);
  const pickerSearchRef = useRef<HTMLInputElement>(null);
  /** Shown once, never refetchable: only the hash is stored server-side. */
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  /** Owned here, not by the drawer, because a refusal at the invite cap has to
   *  force it open — the answer to "where did 60 invites go" is in there. */
  const [historyOpen, setHistoryOpen] = useState(false);
  /** Per-row confirmation targets — mirrors the admin card's own
   *  `rejectTarget`/`resetTarget` pattern: the project's own `AlertDialog`
   *  instead of the browser's un-stylable `window.confirm`, with a button that
   *  repeats the verb instead of a bare "OK". */
  const [transferTarget, setTransferTarget] = useState<RegistrationTeamMember | null>(null);
  const [kickTarget, setKickTarget] = useState<RegistrationTeamMember | null>(null);
  const [disbandOpen, setDisbandOpen] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [draftName, setDraftName] = useState(team.name);
  /** The name this draft was seeded from. A rename that lands from anywhere
   *  (this captain, a co-manager, an organizer) reseeds the field during
   *  render — an effect would render the stale name for one frame first. */
  const [seededName, setSeededName] = useState(team.name);
  const [checkInOpen, setCheckInOpen] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [lockOpen, setLockOpen] = useState(false);
  const [coverCode, setCoverCode] = useState("");
  const [excludeIds, setExcludeIds] = useState<number[]>([]);

  if (seededName !== team.name) {
    setSeededName(team.name);
    setDraftName(team.name);
  }


  /** Fetched only while the dialog is open: nobody else needs this list, and it
   *  goes stale the moment another captain recruits one of them. */
  const freeAgentsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
    queryFn: () => registrationTeamService.listFreeAgents(tournamentId),
    enabled: inviteOpen && inviteMode === "targeted",
  });

  /** Both keys: issuing or revoking an invite moves `cap_used`, and a history
   *  left cached would under-report the ceiling the next time it is opened. */
  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationTeams(workspaceId, tournamentId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationInviteHistory(workspaceId, team.id),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registration(workspaceId, tournamentId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationsList(workspaceId, tournamentId),
      }),
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
      }),
    ]);

  /** Every mutation here reports failure through the code→i18n map: the server's
   *  `msg` is English and this is a public, Russian-first surface. */
  const failure = (err: unknown) => notify.error(translateRegistrationTeamError(tErrors, err));

  const inviteMutation = useMutation({
    mutationFn: () => {
      if (!canEditRoster || !inviteSlot || !selectableSlots.includes(inviteSlot)) {
        throw new Error("Invitation slot is unavailable");
      }
      if (inviteMode === "targeted" && (!targetAgent || freeAgentsQuery.isError)) {
        throw new Error("Select a registered player");
      }
      return registrationTeamService.invite(team.id, {
        slot_code: inviteSlot,
        is_substitute: inviteSubstitute,
        // Omitted rather than nulled for a link invite: the key's presence is what
        // selects the addressed mode server-side.
        ...(inviteMode === "targeted" && targetRegistrationId != null
          ? { target_registration_id: targetRegistrationId }
          : {}),
      });
    },
    onSuccess: async (invite) => {
      notify.success(t("invite.success"));
      // A link invite hands back the raw token exactly once. Keep it on screen
      // instead of closing, or the captain loses it with no way to recover it.
      // A targeted invite carries no token, so there is nothing to keep: close.
      setIssuedToken(invite.token ?? null);
      if (!invite.token) setInviteOpen(false);
      await invalidate();
    },
    onError: (err) => {
      failure(err);
      // The cap counts every invite ever issued, including ones long since
      // revoked, so this refusal is otherwise a dead end: nothing on screen
      // accounts for the ceiling. Open the ledger that does.
      if (registrationTeamErrorCode(err) === "invite_cap_reached") setHistoryOpen(true);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (inviteId: number) => registrationTeamService.revokeInvite(inviteId),
    onSuccess: async () => {
      notify.success(t("invite.revokeSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const kickMutation = useMutation({
    mutationFn: (registrationId: number) => registrationTeamService.kick(team.id, registrationId),
    onSuccess: async () => {
      notify.success(t("member.kickSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const transferMutation = useMutation({
    mutationFn: (registrationId: number) =>
      registrationTeamService.transferCaptaincy(team.id, registrationId),
    onSuccess: async () => {
      notify.success(t("member.makeCaptainSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const leaveMutation = useMutation({
    mutationFn: () => registrationTeamService.leave(team.id),
    onSuccess: async () => {
      notify.success(t("member.leaveSuccess"));
      await invalidate();
    },
    onError: failure,
  });

  const disbandMutation = useMutation({
    mutationFn: () => registrationTeamService.disband(team.id),
    onSuccess: async () => {
      notify.success(t("disband.success"));
      await invalidate();
    },
    onError: failure,
  });

  const uploadImageMutation = useMutation({
    mutationFn: (file: File) => registrationTeamService.uploadImage(team.id, file),
    onSuccess: async () => {
      notify.success(t("myCard.logoSaved"));
      await invalidate();
    },
    onError: failure,
  });

  const deleteImageMutation = useMutation({
    mutationFn: () => registrationTeamService.deleteImage(team.id),
    onSuccess: async () => {
      notify.success(t("myCard.logoRemoved"));
      await invalidate();
    },
    onError: failure,
  });

  const renameMutation = useMutation({
    mutationFn: () => registrationTeamService.rename(team.id, draftName),
    onSuccess: async () => {
      notify.success(t("rename.success"));
      await invalidate();
    },
    onError: failure,
  });

  const placeMutation = useMutation({
    mutationFn: (input: {
      registrationId: number;
      slot_code: string;
      is_substitute?: boolean;
      swap_with_registration_id?: number | null;
    }) =>
      registrationTeamService.placeMember(team.id, input.registrationId, {
        slot_code: input.slot_code,
        is_substitute: input.is_substitute,
        swap_with_registration_id: input.swap_with_registration_id,
      }),
    onSuccess: async () => {
      await invalidate();
    },
    onError: failure,
  });

  const managerMutation = useMutation({
    mutationFn: (input: { registrationId: number; isManager: boolean }) =>
      registrationTeamService.setManager(team.id, input.registrationId, input.isManager),
    onSuccess: async () => {
      await invalidate();
    },
    onError: failure,
  });

  const extendMutation = useMutation({
    mutationFn: (input: { inviteId: number; rotate: boolean }) =>
      registrationTeamService.extendInvite(team.id, input.inviteId, {
        rotate_token: input.rotate,
      }),
    onSuccess: async (invite) => {
      notify.success(t("invite.extendSuccess"));
      setIssuedToken(invite.token ?? null);
      if (invite.token) setInviteOpen(true);
      await invalidate();
    },
    onError: failure,
  });

  const lockMutation = useMutation({
    mutationFn: () => registrationTeamService.lockRoster(team.id),
    onSuccess: async () => {
      notify.success(t("lock.success"));
      setLockOpen(false);
      await invalidate();
    },
    onError: failure,
  });

  const checkInMutation = useMutation({
    mutationFn: () => registrationTeamService.checkInRoster(team.id, excludeIds),
    onSuccess: async () => {
      notify.success(t("checkIn.success"));
      setCheckInOpen(false);
      setExcludeIds([]);
      await invalidate();
    },
    onError: failure,
  });

  const coverMutation = useMutation({
    mutationFn: () =>
      registrationTeamService.coverSubscription(team.id, {
        code: coverCode.trim() || null,
      }),
    onSuccess: async () => {
      notify.success(t("cover.success"));
      setCoverOpen(false);
      setCoverCode("");
      await invalidate();
    },
    onError: failure,
  });

  const busy =
    inviteMutation.isPending || revokeMutation.isPending || kickMutation.isPending ||
    transferMutation.isPending || leaveMutation.isPending || disbandMutation.isPending ||
    renameMutation.isPending || placeMutation.isPending || managerMutation.isPending ||
    extendMutation.isPending || lockMutation.isPending || checkInMutation.isPending ||
    coverMutation.isPending || uploadImageMutation.isPending || deleteImageMutation.isPending;

  const slotLabel = (code: string) => {
    const known = ROSTER_SLOT_CODES.find((candidate) => candidate === code);
    return known ? tSlot(known) : code;
  };

  // Pending is pending: the server reserves a slot for an offer whose clock has
  // run out too (it stays `pending` until someone consumes or revokes it), so
  // discounting expired rows here would advertise a slot the invite call then
  // refuses with `slot_already_offered`.
  const pendingInvites = team.invites.filter((invite) => invite.state === "pending");
  // Open slots count accepted members only; live offers reserve, but do not fill, them.
  const freeSlots = ROSTER_SLOT_CODES.flatMap((code) =>
    Array.from({
      length: Math.max(0, (team.open_slots[code] ?? 0) -
        pendingInvites.filter((invite) => !invite.is_substitute && invite.slot_code === code).length),
    }, () => code),
  );
  const offerableSlots = ROSTER_SLOT_CODES.filter((code) => freeSlots.includes(code));
  const starters = team.members.filter((member) => !member.is_substitute);
  const starterCapacity = starters.length + Object.values(team.open_slots).reduce((sum, count) => sum + count, 0);
  /** Every slot code this roster actually uses, reconstructed from the rows that
   *  hold one. A substitute covers a slot that is by definition FULL, so
   *  `open_slots` — the starter shortfall — can never name it: on a complete
   *  roster it is empty, which left the bench with nothing to select. */
  const shapeSlots = new Set<string>([
    ...Object.keys(team.open_slots),
    ...team.members.map((member) => member.slot_code ?? ""),
    ...team.invites.map((invite) => invite.slot_code),
  ]);
  const benchSlots = ROSTER_SLOT_CODES.filter((code) => shapeSlots.has(code));
  /** Pending substitute offers reserve a bench place — the same arithmetic
   *  `can_offer` does server-side, so the checkbox never promises a seat the
   *  server answers `bench_full` for. */
  const freeBenchCount = Math.max(0, team.max_substitutes - team.substitutes_used -
    pendingInvites.filter((invite) => invite.is_substitute).length);
  const benchOpen = freeBenchCount > 0;
  const selectableSlots = inviteSubstitute ? benchSlots : offerableSlots;
  /** Filtered in memory: this is tens of rows at most, and a round-trip per
   *  keystroke would out-cost the whole list. */
  const freeAgents = freeAgentsQuery.data?.items ?? [];
  const pickerNeedle = pickerSearch.trim().toLowerCase();
  const matchingAgents = pickerNeedle
    ? freeAgents.filter((agent) => agent.battle_tag.toLowerCase().includes(pickerNeedle))
    : freeAgents;
  const targetAgent =
    freeAgents.find((agent) => agent.registration_id === targetRegistrationId) ?? null;
  /** The crest is only writable while the roster still is: the server refuses a
   *  terminal or already-exported team with `team_not_forming` /
   *  `team_already_exported`, so offering the control would be a dead end. */
  const viewerMember = team.members.find(
    (member) => member.registration_id === viewerRegistrationId,
  );
  const isStaff = isCaptain || viewerMember?.is_manager === true;
  const locked = team.roster_locked_at != null;
  const status = getRegistrationTeamStatus(team);
  const active = status === "forming" || status === "complete";
  const rosterAvailable = active && !locked && registrationOpen;
  const canEditRoster = isStaff && rosterAvailable;
  const canCheckIn = isStaff && active && checkInAvailable;
  const canCover = isStaff && active && (registrationOpen || checkInAvailable);
  const logoEditable = canEditRoster && !busy;
  const blockingReason = !active ? t(`myCard.blocked.${status}`)
    : locked ? t("myCard.blocked.locked")
    : !registrationOpen ? t("myCard.blocked.closed") : null;
  const openInvite = (code: RosterSlotCode | null, substitute = false) => {
    setInviteSubstitute(substitute);
    setInviteSlot(code);
    setInviteMode("link");
    setIssuedToken(null);
    setPickerSearch("");
    setTargetRegistrationId(null);
    setInviteValidation(null);
    setInviteOpen(true);
  };

  return (
    <section className="relative grid gap-3 overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 shadow-md backdrop-blur-md sm:p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <EditableAvatar
            src={team.image_url}
            name={team.name}
            size={44}
            shape="rounded"
            editable={logoEditable}
            busy={uploadImageMutation.isPending || deleteImageMutation.isPending}
            onSelectFile={(file) => uploadImageMutation.mutate(file)}
            onDelete={team.image_url ? () => deleteImageMutation.mutate() : undefined}
            maxSizeBytes={MAX_AVATAR_BYTES}
            onError={(message) => notify.error(message)}
            labels={{
              change: t("create.logoChange"),
              upload: t("create.logoUpload"),
              edit: t("create.logoEdit"),
              drop: t("create.logoDrop"),
              remove: t("create.logoRemove"),
              unsupportedType: t("create.logoUnsupported"),
              tooLarge: t("create.logoTooLarge", {
                mb: Math.round(MAX_AVATAR_BYTES / (1024 * 1024)),
              }),
            }}
          />
          <div className="grid min-w-0 gap-0.5">
            {canEditRoster ? (
              <form
                className="flex min-w-0 items-center gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (draftName.trim() && draftName.trim() !== team.name) {
                    renameMutation.mutate();
                  }
                }}
              >
                <Input
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  aria-label={t("rename.save")}
                  className="h-8 min-w-0"
                />
                <Button
                  type="submit"
                  size="sm"
                  disabled={busy || draftName.trim() === team.name || !draftName.trim()}
                >
                  {t("rename.save")}
                </Button>
              </form>
            ) : (
              <h3 className="truncate text-base font-semibold">{team.name}</h3>
            )}
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("myCard.rosterCount", { filled: starters.length, total: starterCapacity })}
            </p>
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">
              {team.is_complete
                ? t("list.complete")
                : t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}
            </p>
            {typeof team.checked_in_count === "number" && (team.check_in_total ?? 0) > 0 && (
              <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("checkIn.counts", {
                  done: team.checked_in_count,
                  total: team.check_in_total ?? 0,
                })}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {locked && (
            <span className="rounded-full border border-[color:var(--aqt-border)] px-2.5 py-0.5 text-xs">
              {t("lock.locked")}
            </span>
          )}
          {team.subscription_covered && (
            <span className="rounded-full border border-[color:var(--aqt-teal)]/40 px-2.5 py-0.5 text-xs text-[color:var(--aqt-teal)]">
              {t("cover.covered")}
            </span>
          )}
          {team.admission && team.admission !== "pending" && (
            <span className="rounded-full border border-[color:var(--aqt-border)] px-2.5 py-0.5 text-xs">
              {t(`admission.${team.admission}`)}
            </span>
          )}
          <span
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-xs font-medium",
              REGISTRATION_TEAM_STATUS_TONE[status]
            )}
          >
            {t(`status.${status}`)}
          </span>
        </div>
      </header>

      {/* Why an action is missing, said once at the top instead of as a dead
          button per row: the roster stops being editable for four different
          reasons and none of them are visible from the buttons alone. */}
      {blockingReason && (
        <p
          role="status"
          className="rounded-lg border border-[color:var(--aqt-border)] bg-muted/20 px-3 py-2 text-xs text-[color:var(--aqt-fg-muted)]"
        >
          {blockingReason}
        </p>
      )}
      {team.rejection_reason && (
        <p className="rounded-lg border border-[color:var(--aqt-rose)]/40 bg-[color:var(--aqt-rose)]/10 px-3 py-2 text-xs text-[color:var(--aqt-rose)]">
          {t("myCard.rejectionReason", { reason: team.rejection_reason })}
        </p>
      )}

      {(team.eligibility_issues?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-[color:var(--aqt-amber)]/40 bg-[color:var(--aqt-amber)]/10 px-3 py-2 text-xs">
          <p className="font-medium">{t("eligibility.title")}</p>
          <ul className="mt-1 grid gap-0.5">
            {team.eligibility_issues!.map((issue, index) => (
              <li key={`${issue.code}-${issue.registration_id ?? "team"}-${index}`}>
                {tErrors.has?.(issue.code as never)
                  ? tErrors(issue.code as never)
                  : issue.code}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="divide-y divide-[color:var(--aqt-border)]">
        {team.members.map((member) => (
          <li
            key={member.registration_id}
            className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0"
          >
            <RosterSlotGlyph code={member.slot_code} />
            <span className="font-medium">{member.display_name ?? member.battle_tag}</span>
            {member.is_captain && (
              <span className="inline-flex items-center gap-1 text-xs text-[color:var(--aqt-amber)]">
                <Crown className="size-3.5" aria-hidden />
                {t("member.captain")}
              </span>
            )}
            {member.is_manager && !member.is_captain && (
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("member.manager")}
              </span>
            )}
            {member.is_substitute && (
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("member.substitute")}
              </span>
            )}
            {canEditRoster && !member.is_captain && (
              <span className="ml-auto flex flex-wrap gap-1">
                {canEditRoster && member.slot_code && (
                  <select
                    className="h-8 rounded-md border border-[color:var(--aqt-border)] bg-transparent px-2 text-xs"
                    aria-label={t("invite.slotLabel")}
                    value={member.slot_code}
                    disabled={busy}
                    onChange={(event) =>
                      placeMutation.mutate({
                        registrationId: member.registration_id,
                        slot_code: event.target.value,
                        is_substitute: member.is_substitute,
                      })
                    }
                  >
                    {ROSTER_SLOT_CODES.map((code) => (
                      <option key={code} value={code}>
                        {slotLabel(code)}
                      </option>
                    ))}
                  </select>
                )}
                {canEditRoster && member.slot_code && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      placeMutation.mutate({
                        registrationId: member.registration_id,
                        slot_code: member.slot_code as string,
                        is_substitute: !member.is_substitute,
                      })
                    }
                  >
                    {member.is_substitute ? t("member.toStart") : t("member.toBench")}
                  </Button>
                )}
                {isCaptain && canEditRoster && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      managerMutation.mutate({
                        registrationId: member.registration_id,
                        isManager: !member.is_manager,
                      })
                    }
                  >
                    {member.is_manager ? t("member.removeManager") : t("member.makeManager")}
                  </Button>
                )}
                {isCaptain && canEditRoster && !member.is_substitute && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => setTransferTarget(member)}
                  >
                    <Crown className="size-3.5" aria-hidden />
                    {t("member.makeCaptain")}
                  </Button>
                )}
                {canEditRoster && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => setKickTarget(member)}
                  >
                    <UserMinus className="size-3.5" aria-hidden />
                    {t("member.kick")}
                  </Button>
                )}
              </span>
            )}
          </li>
        ))}
        {/* A slot nobody holds and nobody was offered: the roster's own gap, with
            the action that fills it on the row rather than behind one generic
            "invite" button that then asks which slot. */}
        {freeSlots.map((code, index) => (
          <li
            key={`free-${code}-${index}`}
            className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0"
          >
            <RosterSlotGlyph code={code} />
            <span className="text-[color:var(--aqt-fg-muted)]">{t("list.openSlot")}</span>
            <span className="text-xs text-[color:var(--aqt-fg-muted)]">{slotLabel(code)}</span>
            {canEditRoster && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="ml-auto"
                disabled={busy}
                onClick={() => openInvite(code)}
              >
                <UserPlus className="size-3.5" aria-hidden />
                {t("invite.actionSlot", { slot: slotLabel(code) })}
              </Button>
            )}
          </li>
        ))}
        {benchOpen && (
          <li className="flex flex-wrap items-center gap-2 py-2.5 text-sm first:pt-0 last:pb-0">
            <span className="text-[color:var(--aqt-fg-muted)]">
              {t("list.substitutes", { used: team.substitutes_used, max: team.max_substitutes })}
            </span>
            {canEditRoster && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="ml-auto"
                disabled={busy}
                onClick={() => openInvite(benchSlots[0] ?? null, true)}
              >
                <UserPlus className="size-3.5" aria-hidden />
                {t("invite.actionBench")}
              </Button>
            )}
          </li>
        )}
      </ul>

      {isStaff && (
        <div className="grid gap-2">
          <span className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
            {t("invite.title")}
          </span>
          {pendingInvites.length === 0 ? (
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("invite.pendingEmpty")}</p>
          ) : (
            <ul className="divide-y divide-[color:var(--aqt-border)]">
              {pendingInvites.map((invite) => (
                <li
                  key={invite.id}
                  className="flex flex-wrap items-center gap-2 border-l-2 border-[color:var(--aqt-amber)]/50 py-2.5 pl-3 text-sm first:pt-0 last:pb-0"
                >
                  <RosterSlotGlyph code={invite.slot_code} />
                  <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                    {invite.target_battle_tag
                      ? t("invite.targetLabel", { name: invite.target_battle_tag })
                      : t("invite.linkLabel")}
                  </span>
                  {invite.is_substitute && (
                    <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                      {t("member.substitute")}
                    </span>
                  )}
                  <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                    {t(`inviteState.${invite.state}`)}
                  </span>
                  {invite.expires_at && (
                    <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                      {t("invite.expiresAt", {
                        date: new Date(invite.expires_at).toLocaleDateString(),
                      })}
                    </span>
                  )}
                  <span className="ml-auto flex flex-wrap gap-1">
                    {canEditRoster && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => {
                          extendMutation.mutate({ inviteId: invite.id, rotate: false });
                        }}
                      >
                        {t("invite.extend")}
                      </Button>
                    )}
                    {canEditRoster && invite.is_link && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => {
                          extendMutation.mutate({ inviteId: invite.id, rotate: true });
                        }}
                      >
                        {t("invite.rotate")}
                      </Button>
                    )}
                    {canEditRoster && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => revokeMutation.mutate(invite.id)}
                      >
                        {t("invite.revoke")}
                      </Button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* The ledger's trigger lives in the actions row rather than as its own
          row above it: it opens a drawer now, so it is an action like the two
          beside it, and the card is one orphan row shorter for it. */}
      <footer className="flex flex-wrap gap-2">
        {canEditRoster && (offerableSlots.length > 0 || benchOpen) && (
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => {
              const substituteOnly = offerableSlots.length === 0;
              openInvite(
                (substituteOnly ? benchSlots : offerableSlots)[0] ?? null,
                substituteOnly
              );
            }}
          >
            <UserPlus className="size-4" aria-hidden />
            {t("invite.action")}
          </Button>
        )}
        {isCaptain && canEditRoster && team.is_complete && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setLockOpen(true)}
          >
            <Lock className="size-4" aria-hidden />
            {t("lock.action")}
          </Button>
        )}
        {canCheckIn && team.members.some((member) => !member.checked_in) && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => {
              setExcludeIds([]);
              setCheckInOpen(true);
            }}
          >
            <UserCheck className="size-4" aria-hidden />
            {t("checkIn.action")}
          </Button>
        )}
        {canCover && subscriptionScope === "team" && !team.subscription_covered && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setCoverOpen(true)}
          >
            {t("cover.action")}
          </Button>
        )}
        {/* Ending the team and leaving it are both roster writes: the server
            refuses either once the team is terminal, exported, locked or the
            window is closed, so the blocked explanation above stands in for
            them rather than a button that can only fail. */}
        {canEditRoster || (!isCaptain && rosterAvailable) ? (
          isCaptain ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setDisbandOpen(true)}
            >
              <Trash2 className="size-4" aria-hidden />
              {t("disband.action")}
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setLeaveOpen(true)}
            >
              <LogOut className="size-4" aria-hidden />
              {t("member.leave")}
            </Button>
          )
        ) : null}
        {isStaff && (
          <InviteHistorySection
            workspaceId={workspaceId}
            teamId={team.id}
            open={historyOpen}
            onOpenChange={setHistoryOpen}
          />
        )}
      </footer>

      {/* Derived, not synced: a roster that freezes while the dialog is open
          (exported, rejected, locked, window closed) closes it, because every
          write it can still submit is one the server now refuses. */}
      <Dialog open={inviteOpen && canEditRoster} onOpenChange={setInviteOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogTitle>{t("invite.title")}</DialogTitle>

          {issuedToken ? (
            <div className="grid gap-2">
              <p className="text-sm font-medium">{t("invite.tokenTitle")}</p>
              <p className="text-xs text-warning">{t("invite.tokenHint")}</p>
              {/* The link, not the bare token: the token is a credential, not an
                  instruction, and a recipient handed one had nowhere to put it. */}
              <code className="block overflow-x-auto rounded-lg border border-[color:var(--aqt-border)] bg-muted/30 px-3 py-2 text-xs">
                {buildInviteLink(issuedToken)}
              </code>
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(buildInviteLink(issuedToken));
                  notify.success(t("invite.copied"));
                }}
              >
                <Copy className="size-4" aria-hidden />
                {t("invite.copy")}
              </Button>
            </div>
          ) : (
            <div className="grid gap-3">
              {/* Two named modes, not one dialog that silently becomes a link
                  when nobody is selected: the two invites differ in who can use
                  them, and that choice must be made on purpose. */}
              <fieldset className="grid gap-1.5">
                <legend className="text-sm font-medium">{t("invite.modeLabel")}</legend>
                <div className="flex flex-wrap gap-2">
                  {(["link", "targeted"] as const).map((mode) => (
                    <label
                      key={mode}
                      className="block cursor-pointer active:scale-[0.96] transition-transform duration-150 ease-out"
                    >
                      <input
                        type="radio"
                        name="invite-mode"
                        value={mode}
                        checked={inviteMode === mode}
                        onChange={() => {
                          setInviteMode(mode);
                          setTargetRegistrationId(null);
                          setInviteValidation(null);
                        }}
                        className="peer sr-only"
                      />
                      <span
                        className={cn(
                          "block rounded-lg border px-3 py-1.5 text-sm transition-colors",
                          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--aqt-teal)]",
                          inviteMode === mode
                            ? "border-[color:var(--aqt-accent)] bg-[color:color-mix(in_srgb,var(--aqt-accent)_12%,transparent)]"
                            : "border-[color:var(--aqt-border)] hover:bg-muted/40",
                        )}
                      >
                        {mode === "link" ? t("invite.modeLink") : t("invite.modeAccount")}
                      </span>
                    </label>
                  ))}
                </div>
                <p className="text-xs text-[color:var(--aqt-fg-muted)]">
                  {inviteMode === "link" ? t("invite.modeLinkHint") : t("invite.modeAccountHint")}
                </p>
              </fieldset>

              <fieldset className="grid gap-1.5">
                <legend className="text-sm font-medium">{t("invite.slotLabel")}</legend>
                <div className="flex flex-wrap gap-2">
                  {selectableSlots.map((code) => {
                    const selected = inviteSlot === code;
                    return (
                      <label
                        key={code}
                        className="block cursor-pointer active:scale-[0.96] transition-transform duration-150 ease-out"
                      >
                        <input
                          type="radio"
                          name="invite-slot"
                          value={code}
                          checked={selected}
                          onChange={() => setInviteSlot(code)}
                          className="peer sr-only"
                        />
                        <span
                          className={cn(
                            "block rounded-lg border px-3 py-1.5 text-sm transition-colors",
                            "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--aqt-teal)]",
                            selected
                              ? "border-[color:var(--aqt-accent)] bg-[color:color-mix(in_srgb,var(--aqt-accent)_12%,transparent)]"
                              : "border-[color:var(--aqt-border)] hover:bg-muted/40",
                          )}
                        >
                          {slotLabel(code)}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>

              {benchOpen && (
                <Label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={inviteSubstitute}
                    onCheckedChange={(checked) => {
                      const substitute = checked === true;
                      setInviteSubstitute(substitute);
                      // The two modes offer different slot lists; a selection kept
                      // across the toggle can leave no radio checked at all.
                      const next = substitute ? benchSlots : offerableSlots;
                      setInviteSlot((current) =>
                        current && next.includes(current) ? current : (next[0] ?? null)
                      );
                    }}
                  />
                  {t("invite.substituteLabel")}
                </Label>
              )}

              {inviteMode === "targeted" && (
              <div className="grid gap-1.5">
                <span className="text-sm font-medium">{t("picker.label")}</span>
                <Input
                  ref={pickerSearchRef}
                  value={pickerSearch}
                  onChange={(event) => setPickerSearch(event.target.value)}
                  placeholder={t("picker.search")}
                  aria-label={t("picker.search")}
                />
                {targetAgent && (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{t("picker.selected", { name: targetAgent.battle_tag })}</span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setTargetRegistrationId(null)}
                    >
                      {t("picker.clear")}
                    </Button>
                  </div>
                )}
                {/* An empty roster of free agents and an empty search result are
                    different dead ends: one waits for registrations, the other
                    only needs a different query. */}
                {freeAgentsQuery.isError ? (
                  /* A failed read is not an empty pool: one says "nobody to
                     recruit", the other only needs the request again. */
                  <p role="alert" className="flex flex-wrap items-center gap-2 text-xs text-[color:var(--aqt-rose)]">
                    {t("picker.loadError")}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void freeAgentsQuery.refetch()}
                    >
                      {tCommon("retry")}
                    </Button>
                  </p>
                ) : null}
                {!freeAgentsQuery.isLoading && !freeAgentsQuery.isError && freeAgents.length === 0 && (
                  <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("picker.empty")}</p>
                )}
                {freeAgents.length > 0 && matchingAgents.length === 0 && (
                  <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("picker.noMatch")}</p>
                )}
                {matchingAgents.length > 0 && (
                  <fieldset>
                    <legend className="sr-only">{t("picker.label")}</legend>
                    <ul className="grid max-h-48 gap-1 overflow-y-auto">
                      {matchingAgents.map((agent) => {
                        const selected = targetRegistrationId === agent.registration_id;
                        return (
                          <li key={agent.registration_id}>
                            <label className="block cursor-pointer active:scale-[0.96] transition-transform duration-150 ease-out">
                              <input
                                type="radio"
                                name="invite-target-agent"
                                value={agent.registration_id}
                                checked={selected}
                                onChange={() => setTargetRegistrationId(agent.registration_id)}
                                className="peer sr-only"
                              />
                              <span
                                className={cn(
                                  "flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm transition-colors",
                                  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[color:var(--aqt-teal)]",
                                  selected
                                    ? "border-[color:var(--aqt-accent)] bg-[color:color-mix(in_srgb,var(--aqt-accent)_12%,transparent)]"
                                    : "border-[color:var(--aqt-border)] hover:bg-muted/40",
                                )}
                              >
                                <span className="truncate">{agent.battle_tag}</span>
                                {/* Roles on the row: the captain is filling one specific
                                    slot and should spot a tank without opening a profile. */}
                                {agent.roles.map((role) => (
                                  <span
                                    key={role}
                                    className="rounded-full border border-[color:var(--aqt-border-2)] px-2 py-0.5 text-label text-[color:var(--aqt-fg-muted)]"
                                  >
                                    {slotLabel(role)}
                                  </span>
                                ))}
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </fieldset>
                )}
              </div>
              )}

              {inviteValidation && (
                <p role="alert" className="text-xs text-[color:var(--aqt-rose)]">
                  {inviteValidation}
                </p>
              )}
              <Button
                type="button"
                /* Enabled until the request starts: a disabled submit hides what
                   is missing, so the unmade choice is named instead. */
                disabled={busy || !inviteSlot}
                onClick={() => {
                  if (inviteMode === "targeted" && targetRegistrationId == null) {
                    setInviteValidation(t("picker.required"));
                    pickerSearchRef.current?.focus();
                    return;
                  }
                  setInviteValidation(null);
                  inviteMutation.mutate();
                }}
              >
                {t("invite.submit")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={transferTarget != null}
        onOpenChange={(open) => !open && setTransferTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("member.makeCaptainConfirm", {
                name: transferTarget
                  ? (transferTarget.display_name ?? transferTarget.battle_tag ?? "")
                  : ""
              })}
            </AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={transferMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={transferMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!transferTarget) return;
                transferMutation.mutate(transferTarget.registration_id);
                setTransferTarget(null);
              }}
            >
              {t("member.makeCaptain")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={kickTarget != null} onOpenChange={(open) => !open && setKickTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("member.kickConfirm", {
                name: kickTarget ? (kickTarget.display_name ?? kickTarget.battle_tag ?? "") : ""
              })}
            </AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={kickMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={kickMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (!kickTarget) return;
                kickMutation.mutate(kickTarget.registration_id);
                setKickTarget(null);
              }}
            >
              {t("member.kick")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={disbandOpen} onOpenChange={setDisbandOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("disband.confirm")}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={disbandMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={disbandMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                disbandMutation.mutate();
              }}
            >
              {t("disband.action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={lockOpen} onOpenChange={setLockOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("lock.action")}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={lockMutation.isPending}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={lockMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                lockMutation.mutate();
              }}
            >
              {t("lock.action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={checkInOpen} onOpenChange={setCheckInOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogTitle>{t("checkIn.action")}</DialogTitle>
          <ul className="grid gap-2">
            {team.members
              .filter((member) => !member.checked_in)
              .map((member) => {
                const excluded = excludeIds.includes(member.registration_id);
                return (
                  <li key={member.registration_id}>
                    <Label className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={excluded}
                        onCheckedChange={(checked) => {
                          const on = checked === true;
                          setExcludeIds((current) =>
                            on
                              ? [...current, member.registration_id]
                              : current.filter((id) => id !== member.registration_id),
                          );
                        }}
                      />
                      {t("checkIn.exclude", {
                        name: member.display_name ?? member.battle_tag ?? "",
                      })}
                    </Label>
                  </li>
                );
              })}
          </ul>
          <Button type="button" disabled={busy} onClick={() => checkInMutation.mutate()}>
            {t("checkIn.action")}
          </Button>
        </DialogContent>
      </Dialog>

      <Dialog open={coverOpen} onOpenChange={setCoverOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogTitle>{t("cover.action")}</DialogTitle>
          <Label className="grid gap-1.5 text-sm">
            {t("cover.code")}
            <Input value={coverCode} onChange={(event) => setCoverCode(event.target.value)} />
          </Label>
          <Button type="button" disabled={busy} onClick={() => coverMutation.mutate()}>
            {t("cover.submit")}
          </Button>
        </DialogContent>
      </Dialog>

      <AlertDialog open={leaveOpen} onOpenChange={setLeaveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("member.leaveConfirm")}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={leaveMutation.isPending}>
              {tCommon("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={leaveMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                leaveMutation.mutate();
              }}
            >
              {t("member.leave")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
