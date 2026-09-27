"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type Dispatch, type SetStateAction } from "react";

import { notify } from "@/lib/notify";
import { registrationTeamErrorCode } from "@/lib/registration/team-errors";
import type { RosterSlotCode } from "@/lib/roster/shape";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationFreeAgent } from "@/types/registration-team.types";

export type InviteMode = "link" | "targeted";

/** Everything the invite dialog renders and drives. */
export interface MyTeamInviteController {
  open: boolean;
  setOpen: (open: boolean) => void;
  mode: InviteMode;
  selectMode: (mode: InviteMode) => void;
  slot: RosterSlotCode | null;
  setSlot: (code: RosterSlotCode) => void;
  substitute: boolean;
  toggleSubstitute: (substitute: boolean) => void;
  /** Slot codes offerable in the current mode: bench shape or starter gaps. */
  selectableSlots: RosterSlotCode[];
  search: string;
  setSearch: (value: string) => void;
  targetRegistrationId: number | null;
  setTargetRegistrationId: (registrationId: number | null) => void;
  targetAgent: RegistrationFreeAgent | null;
  /** Free agents left after the search box narrows them. */
  matchingAgents: RegistrationFreeAgent[];
  /** Size of the unfiltered pool: an empty pool and an empty search differ. */
  freeAgentCount: number;
  agentsLoading: boolean;
  agentsError: boolean;
  retryAgents: () => void;
  validation: string | null;
  issuedToken: string | null;
  setIssuedToken: Dispatch<SetStateAction<string | null>>;
  isPending: boolean;
  /** Seeds the dialog for one slot and opens it. */
  openInvite: (code: RosterSlotCode | null, substitute?: boolean) => void;
  /** `false` when a targeted invite still has no addressee. */
  submit: () => boolean;
}

interface UseMyTeamInviteInput {
  workspaceId: number;
  tournamentId: number;
  teamId: number;
  /** Whether a roster write can still land at all. The dialog closes with it,
   *  and the submit refuses rather than posting something the server denies. */
  canEditRoster: boolean;
  offerableSlots: RosterSlotCode[];
  benchSlots: RosterSlotCode[];
  invalidate: () => Promise<unknown>;
  failure: (err: unknown) => void;
  /** The cap counts every invite ever issued, including ones long since
   *  revoked, so that refusal is otherwise a dead end: nothing on screen
   *  accounts for the ceiling. Opens the ledger that does. */
  onInviteCapReached: () => void;
}

/**
 * The invite dialog's whole state: which kind of offer is being made, for which
 * slot, to whom, and the token a link invite hands back exactly once.
 */
export function useMyTeamInvite({
  workspaceId,
  tournamentId,
  teamId,
  canEditRoster,
  offerableSlots,
  benchSlots,
  invalidate,
  failure,
  onInviteCapReached,
}: UseMyTeamInviteInput): MyTeamInviteController {
  const t = useTranslations("registrationTeams");

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteMode, setInviteMode] = useState<InviteMode>("link");
  const [inviteSlot, setInviteSlot] = useState<RosterSlotCode | null>(null);
  const [inviteSubstitute, setInviteSubstitute] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  /** A registration id, not an account id. Targeted mode requires a selection. */
  const [targetRegistrationId, setTargetRegistrationId] = useState<number | null>(null);
  /** Named rather than enforced by a dead submit: an unmade choice must say so. */
  const [inviteValidation, setInviteValidation] = useState<string | null>(null);
  /** Shown once, never refetchable: only the hash is stored server-side. */
  const [issuedToken, setIssuedToken] = useState<string | null>(null);

  /** Fetched only while the dialog is open: nobody else needs this list, and it
   *  goes stale the moment another captain recruits one of them. */
  const freeAgentsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationFreeAgents(workspaceId, tournamentId),
    queryFn: () => registrationTeamService.listFreeAgents(tournamentId),
    enabled: inviteOpen && inviteMode === "targeted",
  });

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

  const inviteMutation = useMutation({
    mutationFn: () => {
      if (!canEditRoster || !inviteSlot || !selectableSlots.includes(inviteSlot)) {
        throw new Error("Invitation slot is unavailable");
      }
      if (inviteMode === "targeted" && (!targetAgent || freeAgentsQuery.isError)) {
        throw new Error("Select a registered player");
      }
      return registrationTeamService.invite(teamId, {
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
      if (registrationTeamErrorCode(err) === "invite_cap_reached") onInviteCapReached();
    },
  });

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

  /** Submitting names the unmade choice rather than hiding behind a dead
   *  button. Returns `false` when the addressee is the thing still missing, so
   *  the dialog can put the caret back in its picker. */
  const submitInvite = () => {
    if (inviteMode === "targeted" && targetRegistrationId == null) {
      setInviteValidation(t("picker.required"));
      return false;
    }
    setInviteValidation(null);
    inviteMutation.mutate();
    return true;
  };

  /** The two modes offer different slot lists; a selection kept across the
   *  toggle can leave no radio checked at all. */
  const toggleSubstitute = (substitute: boolean) => {
    setInviteSubstitute(substitute);
    const next = substitute ? benchSlots : offerableSlots;
    setInviteSlot((current) => (current && next.includes(current) ? current : (next[0] ?? null)));
  };

  const selectMode = (mode: InviteMode) => {
    setInviteMode(mode);
    setTargetRegistrationId(null);
    setInviteValidation(null);
  };

  return {
    open: inviteOpen,
    setOpen: setInviteOpen,
    mode: inviteMode,
    selectMode,
    slot: inviteSlot,
    setSlot: setInviteSlot,
    substitute: inviteSubstitute,
    toggleSubstitute,
    selectableSlots,
    search: pickerSearch,
    setSearch: setPickerSearch,
    targetRegistrationId,
    setTargetRegistrationId,
    targetAgent,
    matchingAgents,
    freeAgentCount: freeAgents.length,
    agentsLoading: freeAgentsQuery.isLoading,
    agentsError: freeAgentsQuery.isError,
    retryAgents: () => void freeAgentsQuery.refetch(),
    validation: inviteValidation,
    issuedToken,
    setIssuedToken,
    isPending: inviteMutation.isPending,
    openInvite,
    submit: submitInvite,
  };
}
