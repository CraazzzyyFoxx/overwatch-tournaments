"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import pickBanService from "@/services/pickBan.service";
import type { PickBanKind, PickBanState, PickBanSubmissionItem } from "@/types/tournament.types";

import { DRAFT_SAVE_DELAY_MS, stepSubmissions } from "./pick-ban-model";
import type { PickBanItemLike } from "./PickBanGrid";

/** Whom a member pick is made for, when the viewer may pick for more than one player (spec §11.6 R4-3, R4-9). */
export function PickBanMemberChooser({
  members,
  value,
  onChange
}: Readonly<{
  members: { id: number; name: string }[];
  value: number | null;
  onChange: (memberId: number) => void;
}>) {
  const t = useTranslations("pickBan.room");
  return (
    <div className="flex flex-col gap-1" role="group" aria-label={t("member.pickFor")}>
      <Eyebrow>{t("member.pickFor")}</Eyebrow>
      <div className="flex flex-wrap gap-1">
        {members.map((member) => (
          <Button
            key={member.id}
            type="button"
            size="sm"
            variant={member.id === value ? "accent" : "outline"}
            aria-pressed={member.id === value}
            onClick={() => onChange(member.id)}
          >
            {member.name}
          </Button>
        ))}
      </div>
    </div>
  );
}

/**
 * An assignment step (spec §11.6 R4-1, model c): a team's captain gives each player one of the heroes the team
 * picked; the offer per player is the server's (`member_eligible`, Fearless applied). A host assigns for any team
 * still owing. Each choice is saved unlocked as it is made (the server refuses one that leaves no full assignment),
 * so a refresh reads it back and the clock keeps it; what nobody locks in time the clock completes at random.
 */
export function PickBanAssignBoard({
  kind,
  encounterId,
  state,
  itemsById,
  isAdmin,
  queryKey,
  teamName,
  header
}: Readonly<{
  kind: PickBanKind;
  encounterId: number;
  state: PickBanState;
  itemsById: Record<number, PickBanItemLike | undefined>;
  isAdmin: boolean;
  queryKey: unknown[];
  teamName: (teamId: number) => string;
  header: React.ReactNode;
}>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const own = state.viewer_can_act && state.viewer_team_id != null ? [state.viewer_team_id] : [];
  const teams = isAdmin ? [...new Set([...own, ...state.acting_team_ids])] : own;
  const stepIndex = state.current_step_index ?? -1;
  const saved = stepSubmissions(state.submissions, stepIndex);
  // member -> hero per team as edited on this step; until then, or after a refused save, the server's saved one.
  const [edits, setEdits] = useState<{ step: number; teams: Partial<Record<number, Record<number, number>>> }>({
    step: stepIndex,
    teams: {}
  });
  const saveTimers = useRef<Record<number, number>>({});
  // Teams whose Lock is in flight: their board holds still, so a refused lock can roll back no newer edit.
  const [lockingTeams, setLockingTeams] = useState<number[]>([]);
  // The queue's lifecycle: a closed (unmounted) board sends nothing it still had queued.
  const open = useRef(false);
  useEffect(() => {
    open.current = true;
    return () => {
      open.current = false;
    };
  }, []);
  // Per team, its autosaves in order, one in flight at a time: the server keeps whichever lands last, so a slow save
  // must never land over a newer one. `revision` counts local edits, `sent` is the newest put on the wire; `locking`
  // from the Lock click on, which overtakes them all.
  const teamSaves = useRef<
    Record<
      number,
      { revision: number; sent: number; picks: Record<number, number>; chain: Promise<void>; locking: boolean }
    >
  >({});
  const teamSave = (teamId: number) =>
    (teamSaves.current[teamId] ??= { revision: 0, sent: 0, picks: {}, chain: Promise.resolve(), locking: false });
  const submit = useMutation({
    mutationFn: ({
      teamId,
      picks,
      lock
    }: {
      teamId: number;
      picks: Record<number, number>;
      lock: boolean;
      revision: number;
    }) => {
      const items: PickBanSubmissionItem[] = Object.entries(picks).map(([member, hero]) => ({
        item_id: hero,
        target_player_id: null,
        member_id: Number(member)
      }));
      return own.includes(teamId)
        ? pickBanService.submitDraft(kind, encounterId, { items, lock })
        : adminService.adminPickBanSubmit(encounterId, { kind, encounter_team_id: teamId, items, lock });
    },
    onError: (error, { teamId, revision, lock }) => {
      const team = teamSave(teamId);
      if (lock) {
        team.locking = false;
        setLockingTeams((current) => current.filter((id) => id !== teamId));
      }
      // Moot: the refusal of an autosave a newer edit replaced, or one the lock overtook.
      else if (team.locking || team.revision !== revision) return;
      // Refused: the server's saved assignment is the board again.
      setEdits((current) => ({ ...current, teams: { ...current.teams, [teamId]: undefined } }));
      notify.apiError(error, { title: t("assign.failed") });
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });
  /** Queues a team's autosave behind its earlier ones; when its turn comes it sends the newest edit, unless a turn
   * before already did, the team is locking, or the board has closed. */
  const queueSave = (teamId: number) => {
    const team = teamSave(teamId);
    team.chain = team.chain.then(async () => {
      if (!open.current || team.locking || team.sent === team.revision) return;
      team.sent = team.revision;
      await submit
        .mutateAsync({ teamId, picks: team.picks, lock: false, revision: team.revision })
        .catch(() => {}); // onError has dealt with it
    });
  };
  // Saved like the blind draft tray: a burst of clicks is one debounced save.
  const choose = (teamId: number, picks: Record<number, number>) => {
    const team = teamSave(teamId);
    team.revision += 1;
    team.picks = picks;
    window.clearTimeout(saveTimers.current[teamId]);
    setEdits((current) => ({
      step: stepIndex,
      teams: { ...(current.step === stepIndex ? current.teams : {}), [teamId]: picks }
    }));
    saveTimers.current[teamId] = window.setTimeout(() => queueSave(teamId), DRAFT_SAVE_DELAY_MS);
  };
  // The lock goes at once with the newest draft, never behind an autosave that may not settle: the server orders the
  // writes and refuses any save after the lock. It drops the team's autosaves not yet sent, and sends only once.
  const lockTeam = (teamId: number, picks: Record<number, number>) => {
    const team = teamSave(teamId);
    if (team.locking) return;
    team.locking = true;
    setLockingTeams((current) => [...current, teamId]);
    window.clearTimeout(saveTimers.current[teamId]);
    submit.mutate({ teamId, picks, lock: true, revision: team.revision });
  };
  const heroName = (heroId: number) =>
    itemsById[heroId]?.name ?? t(`${kind}.itemNumber`, { id: heroId });

  return (
    <Card>
      <CardHeader className="flex flex-col gap-4 pb-3">
        {header}
        <CardTitle className="border-t border-[color:var(--aqt-border)] pt-4">
          {t("assign.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {teams.length === 0 ? (
          <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("assign.waiting")}</p>
        ) : null}
        {teams.map((teamId) => {
          const members = state.members.filter((member) => member.encounter_team_id === teamId);
          const teamLocking = lockingTeams.includes(teamId);
          const picks: Record<number, number> =
            (edits.step === stepIndex ? edits.teams[teamId] : undefined) ??
            Object.fromEntries(
              (
                saved.find((row) => row.encounter_team_id === teamId && row.team_member_id == null)?.items ??
                []
              ).flatMap((item) => (item.member_id != null ? [[item.member_id, item.item_id]] : []))
            );
          return (
            <section key={teamId} className="flex flex-col gap-2" aria-label={teamName(teamId)}>
              <Eyebrow>{teamName(teamId)}</Eyebrow>
              {members.map((member) => (
                <div key={member.id} className="flex flex-wrap items-center gap-1">
                  <span className="w-32 truncate text-sm">{member.name}</span>
                  {(state.member_eligible?.[String(member.id)] ?? []).map((heroId) => (
                    <Button
                      key={heroId}
                      type="button"
                      size="sm"
                      disabled={teamLocking}
                      variant={picks[member.id] === heroId ? "accent" : "outline"}
                      aria-pressed={picks[member.id] === heroId}
                      aria-label={t("assign.give", { hero: heroName(heroId), member: member.name })}
                      onClick={() =>
                        choose(teamId, {
                          ...Object.fromEntries(Object.entries(picks).filter(([, hero]) => hero !== heroId)),
                          [member.id]: heroId
                        })
                      }
                    >
                      {heroName(heroId)}
                    </Button>
                  ))}
                </div>
              ))}
              <Button
                size="sm"
                className="self-start"
                disabled={teamLocking || !members.every((member) => picks[member.id] != null)}
                onClick={() => lockTeam(teamId, picks)}
              >
                {teamLocking ? <Spinner className="mr-2" /> : null}
                {t("assign.lock")}
              </Button>
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}
