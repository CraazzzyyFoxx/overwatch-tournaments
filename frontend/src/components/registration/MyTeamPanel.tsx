"use client";

import { Lock, LogOut, Trash2, UserCheck, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import InviteHistorySection from "@/components/registration/InviteHistorySection";
import MyTeamHeader from "@/components/registration/MyTeamHeader";
import MyTeamInviteDialog from "@/components/registration/MyTeamInviteDialog";
import MyTeamInvitesList from "@/components/registration/MyTeamInvitesList";
import MyTeamRosterList from "@/components/registration/MyTeamRosterList";
import { getRegistrationTeamStatus } from "@/lib/registration/team-tone";
import type { RegistrationTeam, RegistrationTeamMember } from "@/types/registration-team.types";

import { buildMyTeamRoster, slotLabelFor } from "./myTeam.model";
import { useMyTeamInvite } from "./useMyTeamInvite";
import { useMyTeamMutations, useMyTeamRefresh } from "./useMyTeamMutations";

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

type ConfirmKind = "transfer" | "kick" | "disband" | "lock" | "leave";

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
  const tErrors = useTranslations("registrationTeams.errors");
  // The same translated slot vocabulary the admin card and the public tab use, so
  // one roster never shows "DPS" in its shortfall and "Урон" on a chip.
  const tSlot = useTranslations("rosterShape.slotCodes");

  /** Owned here, not by the drawer, because a refusal at the invite cap has to
   *  force it open — the answer to "where did 60 invites go" is in there. */
  const [historyOpen, setHistoryOpen] = useState(false);
  /** One confirmation surface for every irreversible roster action — the
   *  project's own `ConfirmDialog` instead of the browser's un-stylable
   *  `window.confirm`, with a button that repeats the verb instead of a bare
   *  "OK". A member-scoped action carries its target here. */
  const [confirming, setConfirming] = useState<
    | { kind: Extract<ConfirmKind, "transfer" | "kick">; member: RegistrationTeamMember }
    | { kind: Exclude<ConfirmKind, "transfer" | "kick"> }
    | null
  >(null);
  const [checkInOpen, setCheckInOpen] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [coverCode, setCoverCode] = useState("");
  const [excludeIds, setExcludeIds] = useState<number[]>([]);

  const {
    pendingInvites,
    freeSlots,
    offerableSlots,
    starters,
    starterCapacity,
    benchSlots,
    benchOpen,
  } = buildMyTeamRoster(team);

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

  const refresh = useMyTeamRefresh(workspaceId, tournamentId, team.id);

  const invite = useMyTeamInvite({
    workspaceId,
    tournamentId,
    teamId: team.id,
    canEditRoster,
    offerableSlots,
    benchSlots,
    invalidate: refresh.invalidate,
    failure: refresh.failure,
    onInviteCapReached: () => setHistoryOpen(true),
  });

  const mutations = useMyTeamMutations({
    teamId: team.id,
    invalidate: refresh.invalidate,
    failure: refresh.failure,
    onExtended: (token) => {
      invite.setIssuedToken(token);
      if (token) invite.setOpen(true);
    },
    onLocked: () => setConfirming(null),
    onCheckedIn: () => {
      setCheckInOpen(false);
      setExcludeIds([]);
    },
    onCovered: () => {
      setCoverOpen(false);
      setCoverCode("");
    },
  });

  const busy =
    invite.isPending || mutations.revokeMutation.isPending || mutations.kickMutation.isPending ||
    mutations.transferMutation.isPending || mutations.leaveMutation.isPending ||
    mutations.disbandMutation.isPending || mutations.renameMutation.isPending ||
    mutations.placeMutation.isPending || mutations.managerMutation.isPending ||
    mutations.extendMutation.isPending || mutations.lockMutation.isPending ||
    mutations.checkInMutation.isPending || mutations.coverMutation.isPending ||
    mutations.uploadImageMutation.isPending || mutations.deleteImageMutation.isPending;

  const logoEditable = canEditRoster && !busy;
  const blockingReason = !active ? t(`myCard.blocked.${status}`)
    : locked ? t("myCard.blocked.locked")
    : !registrationOpen ? t("myCard.blocked.closed") : null;
  const slotLabel = (code: string) => slotLabelFor(code, tSlot);

  // One flat table: the dialog is mounted once and reads whichever row the
  // pending action names. Only the two member-scoped rows interpolate a name.
  const confirmName =
    confirming && "member" in confirming
      ? (confirming.member.display_name ?? confirming.member.battle_tag ?? "")
      : "";
  const CONFIRM_INTENTS: Record<ConfirmKind, ConfirmIntent> = {
    transfer: {
      title: t("member.makeCaptainConfirm", { name: confirmName }),
      description: "",
      confirmLabel: t("member.makeCaptain"),
      tone: "warning"
    },
    kick: {
      title: t("member.kickConfirm", { name: confirmName }),
      description: "",
      confirmLabel: t("member.kick"),
      tone: "danger"
    },
    disband: {
      title: t("disband.confirm"),
      description: "",
      confirmLabel: t("disband.action"),
      tone: "danger"
    },
    lock: {
      title: t("lock.action"),
      description: "",
      confirmLabel: t("lock.action"),
      tone: "warning"
    },
    leave: {
      title: t("member.leaveConfirm"),
      description: "",
      confirmLabel: t("member.leave"),
      tone: "danger"
    }
  };

  return (
    <section className="relative grid gap-3 overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 shadow-md backdrop-blur-md sm:p-5">
      <MyTeamHeader
        team={team}
        starterCount={starters.length}
        starterCapacity={starterCapacity}
        locked={locked}
        canEditRoster={canEditRoster}
        busy={busy}
        logoEditable={logoEditable}
        logoBusy={
          mutations.uploadImageMutation.isPending || mutations.deleteImageMutation.isPending
        }
        tSlot={tSlot}
        onRename={mutations.renameMutation.mutate}
        onUploadLogo={mutations.uploadImageMutation.mutate}
        onDeleteLogo={mutations.deleteImageMutation.mutate}
      />

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

      <MyTeamRosterList
        team={team}
        freeSlots={freeSlots}
        benchSlots={benchSlots}
        benchOpen={benchOpen}
        isCaptain={isCaptain}
        canEditRoster={canEditRoster}
        busy={busy}
        slotLabel={slotLabel}
        onPlace={mutations.placeMutation.mutate}
        onSetManager={mutations.managerMutation.mutate}
        onTransferCaptaincy={(member) => setConfirming({ kind: "transfer", member })}
        onKick={(member) => setConfirming({ kind: "kick", member })}
        onInvite={invite.openInvite}
      />

      {isStaff && (
        <MyTeamInvitesList
          pendingInvites={pendingInvites}
          canEditRoster={canEditRoster}
          busy={busy}
          onExtend={mutations.extendMutation.mutate}
          onRevoke={mutations.revokeMutation.mutate}
        />
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
              invite.openInvite(
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
            onClick={() => setConfirming({ kind: "lock" })}
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
              onClick={() => setConfirming({ kind: "disband" })}
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
              onClick={() => setConfirming({ kind: "leave" })}
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

      <MyTeamInviteDialog
        invite={invite}
        canEditRoster={canEditRoster}
        benchOpen={benchOpen}
        busy={busy}
        slotLabel={slotLabel}
      />

      <ConfirmDialog
        open={confirming != null}
        onOpenChange={(open) => !open && setConfirming(null)}
        intent={CONFIRM_INTENTS[confirming?.kind ?? "leave"]}
        pending={
          mutations.transferMutation.isPending ||
          mutations.kickMutation.isPending ||
          mutations.disbandMutation.isPending ||
          mutations.lockMutation.isPending ||
          mutations.leaveMutation.isPending
        }
        onConfirm={() => {
          if (!confirming) return;
          switch (confirming.kind) {
            case "transfer":
              mutations.transferMutation.mutate(confirming.member.registration_id);
              setConfirming(null);
              break;
            case "kick":
              mutations.kickMutation.mutate(confirming.member.registration_id);
              setConfirming(null);
              break;
            case "disband":
              mutations.disbandMutation.mutate();
              break;
            case "lock":
              mutations.lockMutation.mutate();
              break;
            case "leave":
              mutations.leaveMutation.mutate();
              break;
          }
        }}
      />

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
          <Button
            type="button"
            disabled={busy}
            onClick={() => mutations.checkInMutation.mutate(excludeIds)}
          >
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
          <Button
            type="button"
            disabled={busy}
            onClick={() => mutations.coverMutation.mutate(coverCode)}
          >
            {t("cover.submit")}
          </Button>
        </DialogContent>
      </Dialog>
    </section>
  );
}
