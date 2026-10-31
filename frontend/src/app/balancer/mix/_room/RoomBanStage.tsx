"use client";

import { useEffect, useEffectEvent, useId, useMemo } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Clock, Flag, Lock, Pause, Shield, Shuffle, Users, type LucideIcon } from "lucide-react";

import { useTurnAlert } from "@/app/balancer/mix/_hooks/useTurnAlert";
import { teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanDraftTray } from "@/components/pick-ban/PickBanDraftTray";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanAssignBoard } from "@/components/pick-ban/PickBanMemberTurn";
import { PickBanRevealPanel } from "@/components/pick-ban/PickBanRevealPanel";
import { PickBanCountdown } from "@/components/pick-ban/PickBanCountdown";
import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { PickBanSideChoice } from "@/components/pick-ban/PickBanSideChoice";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { PregameAdminControls } from "@/components/pick-ban/PregameAdminControls";
import {
  CHARACTER_PICK_BAN_KIND,
  isSessionActive,
  memberName,
  pickBanReserveMap,
  stepDeadlineMs,
  stepSubmissions,
  type PickBanSeat
} from "@/components/pick-ban/pick-ban-model";
import { usePickBanController } from "@/components/pick-ban/usePickBanController";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { PickBanAction, PickBanResolvedStep, PickBanState } from "@/types/tournament.types";

import { heroTransitionName } from "./room-model";

/**
 * A live match's hero bans and picks in the room's centre (spec §8, §11): the steps in order, the hero grid (or the
 * side choice, or the captains' assignment), and the bar that confirms the viewer's turn. The teams' bans and heroes
 * land in the columns beside it, where a member step's player is chosen too (`chosenMember`). A host acts for the team
 * on the clock from the same bar, and reaches everything else (a blind ban for an absent captain, a reopen, a reset)
 * through the organizer controls the host menu unfolds here. `onComplete` fires once when the room is done -- the
 * steps finished or a host cancelled it -- so the room re-reads the lobby, which then reads Live.
 */
export function RoomBanStage({
  encounterId,
  workspaceId,
  discipline,
  seats,
  state,
  queryKey,
  heroesById,
  canHost,
  showAdmin,
  chosenMember,
  onComplete
}: Readonly<{
  encounterId: number;
  workspaceId: number;
  discipline: string;
  /** The live match's participations in slot order. */
  seats: readonly PickBanSeat[];
  state: PickBanState & { session: NonNullable<PickBanState["session"]> };
  queryKey: unknown[];
  heroesById: Record<number, PickBanItemLike | undefined>;
  canHost: boolean;
  /** The host unfolded the organizer controls from the room's host menu. */
  showAdmin: boolean;
  /** The player a member step picks for, as chosen on the rosters (`PickBanMember.id`). */
  chosenMember: number | null;
  onComplete: () => void;
}>) {
  const t = useTranslations("mixes.arena.bans");
  const tRoom = useTranslations("mixes.room");
  const tPickBan = useTranslations("pickBan.room");
  const sideHintId = useId();
  const queryClient = useQueryClient();
  const metadata = useDisciplineMetadata(workspaceId, discipline);
  const session = state.session;
  const encounter = useMemo(
    () => ({ workspace_id: workspaceId, discipline, teams: seats }),
    [workspaceId, discipline, seats]
  );
  const room = usePickBanController({
    kind: CHARACTER_PICK_BAN_KIND,
    encounterId,
    encounter,
    state,
    session,
    queryKey,
    itemsById: heroesById,
    isAdmin: canHost,
    chosenMember
  });

  // A pick or an assignment says so in the tab title; a ban keeps its own (spec §11.6 R4-11). Each step (and each
  // reopening of one) is a turn of its own, so two picks of the viewer's in a row alert twice.
  const picking = state.expected_action === "pick" || state.expected_action === "assign";
  const turnStep = state.current_step_index;
  const turnAttempt = turnStep != null ? (stepSubmissions(state.submissions, turnStep)[0]?.attempt ?? 1) : 0;
  useTurnAlert(
    state.viewer_can_act,
    tRoom(picking ? "yourPickTitle" : "yourTurnTitle"),
    `${session.id}:${turnStep}:${turnAttempt}`
  );
  // An effect event: the room hands a fresh callback every render, and the re-read must still happen once.
  const complete = useEffectEvent(onComplete);
  const done = state.is_complete || session.status === "cancelled";
  useEffect(() => {
    if (done) complete();
  }, [done]);

  const step = room.step;
  const open = isSessionActive(session) && !state.is_complete && session.paused_at == null;
  // A host standing in for the one team on the clock of an open team step: the bar answers it through the
  // organizer route (spec §8.4: hosts act for anyone). Member picks already go that way through the board itself.
  const hostAction: PickBanAction | null =
    canHost &&
    open &&
    room.captainAction == null &&
    step != null &&
    !room.isBlindStep &&
    !room.memberStep &&
    !room.assignStep &&
    step.action !== "decider" &&
    step.action !== "assign" &&
    state.acting_team_ids.length === 1
      ? step.action
      : null;
  const hostAct = useMutation({
    mutationFn: (input: { encounter_team_id: number; item_id: number; action: PickBanAction }) =>
      adminService.adminPickBanAct(encounterId, { kind: CHARACTER_PICK_BAN_KIND, ...input }),
    onSuccess: () => room.cancelSelection(),
    onError: (error) => notify.apiError(error, { title: tPickBan("admin.actFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });
  const barAction = state.is_complete ? null : (room.captainAction ?? hostAction);
  // Why the bar has nothing to confirm: a free-order pick waits for a player tapped on the rosters, and on a
  // captains-only pick everyone else is told who answers it.
  const pickHint =
    !open || step?.member == null || barAction != null
      ? null
      : room.choosableMembers.length > 1 && room.actingMemberId == null
        ? t("choosePlayer")
        : step.captains_only === true && !state.viewer_can_act && !canHost
          ? t("captainsPick")
          : null;
  const sideActor = room.captainAction === "side_pick" || hostAction === "side_pick";
  const canSelect = room.canSelect || hostAction != null;
  const title = tRoom(state.sequence.some((candidate) => candidate.action === "pick") ? "picksTitle" : "bansTitle");
  const draftOpen = room.isBlindStep && state.viewer_can_act && !room.draftLocked && !state.is_complete;
  // The viewer's own turn, as the command bar reads it -- without a host standing in for a team.
  const mine = session.paused_at == null && (room.captainAction != null || draftOpen);
  const turnOutline = !mine
    ? undefined
    : step?.action === "ban"
      ? "border-[color:var(--aqt-rose)]/60 ring-2 ring-[color:var(--aqt-rose)]/25"
      : "border-[color:var(--aqt-teal)]/60 ring-2 ring-[color:var(--aqt-teal)]/25";

  const header = (
    <div className="flex flex-col gap-3">
      <h2 className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">{title}</h2>
      <StepStrip state={state} seats={seats} heroesById={heroesById} teamName={room.teamName} />
      <TurnBanner state={state} seats={seats} mine={mine} teamName={room.teamName} />
    </div>
  );

  return (
    <div className="flex flex-col gap-3">
      {room.pendingOpenerTeamId != null ? (
        <div className="flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-caption">
          <Clock className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-[color:var(--aqt-fg-muted)]">
            {tPickBan("electOpener.waiting", { team: room.teamName(room.pendingOpenerTeamId) })}
          </p>
        </div>
      ) : null}

      {room.revealedStep != null ? (
        <PickBanRevealPanel
          kind={CHARACTER_PICK_BAN_KIND}
          step={room.revealedStep}
          submissions={stepSubmissions(state.submissions, room.revealedStep.index)}
          itemsById={heroesById}
          seats={room.seats}
          targetName={room.targetName}
          dispute={state.dispute}
          disputing={room.dispute.pending}
          onDispute={room.dispute.run}
        />
      ) : null}

      {room.isSideStep ? (
        <Card className={turnOutline}>
          <CardHeader className="flex flex-col gap-4 pb-3">
            {header}
            <CardTitle id={sideHintId} className="border-t border-[color:var(--aqt-border)] pt-4">
              {tPickBan("captain.chooseSideHint")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PickBanSideChoice
              labelledBy={sideHintId}
              labels={room.sideLabels}
              value={room.selectedSide}
              size="lg"
              disabled={!sideActor || room.acting || hostAct.isPending}
              onChange={(index) => room.chooseSide(room.selectedSide === index ? null : index)}
            />
          </CardContent>
        </Card>
      ) : room.assignStep ? (
        <PickBanAssignBoard
          kind={CHARACTER_PICK_BAN_KIND}
          encounterId={encounterId}
          state={state}
          itemsById={heroesById}
          isAdmin={canHost}
          queryKey={queryKey}
          teamName={room.teamName}
          header={header}
        />
      ) : (
        <PickBanGrid
          kind={CHARACTER_PICK_BAN_KIND}
          pool={state.pool}
          itemsById={heroesById}
          selectedItemId={room.selectedItemId}
          canSelect={canSelect}
          currentRound={state.current_round}
          slotReserves={pickBanReserveMap(session)}
          eligibleIds={room.eligibleIds}
          draftItemIds={room.draftItemIds}
          onSelect={room.selectTile}
          seats={room.seats}
          header={header}
          characterClasses={metadata.data?.discipline.character_classes}
          itemTransitionName={(entry) =>
            entry.status === "available" ? heroTransitionName(entry.item_id) : undefined
          }
          className={turnOutline}
        />
      )}

      <PickBanUndoControl
        kind={CHARACTER_PICK_BAN_KIND}
        encounterId={encounterId}
        undo={state.undo}
        viewerTeamId={room.viewerTeamId}
        itemsById={heroesById}
        sideLabels={room.sideLabels}
        seats={room.seats}
        invalidateKeys={[queryKey]}
      />

      {canHost && showAdmin ? (
        <PregameAdminControls
          kind={CHARACTER_PICK_BAN_KIND}
          encounterId={encounterId}
          state={state}
          selectedItemId={room.adminSlot.selectedItemId}
          selectedItemName={room.adminSlot.selectedItemName}
          itemsById={heroesById}
          sideLabels={room.sideLabels}
          games={[]}
          blind={room.adminSlot.blind}
          seats={room.seats}
          bestOf={1}
          seriesWins={null}
          onMutated={room.adminSlot.onMutated}
          technicalLoss={false}
        />
      ) : null}

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          teamName={room.teamName}
          captainAction={barAction}
          draft={
            room.isBlindStep && step != null && room.viewerTeamId != null ? (
              <PickBanDraftTray
                kind={CHARACTER_PICK_BAN_KIND}
                step={step}
                items={room.draftItems}
                locked={room.draftLocked}
                dirty={room.draftDirty}
                issues={state.draft_issues}
                locking={room.locking}
                itemsById={heroesById}
                targetName={room.targetName}
                opponentTeamId={room.opponentTeamId}
                opponentProgress={
                  room.opponentTeamId != null ? state.step_progress?.[room.opponentTeamId] : undefined
                }
                opponentName={room.opponentTeamId != null ? room.teamName(room.opponentTeamId) : ""}
                onRemove={room.removeDraftAt}
                onLock={room.lockDraft}
              />
            ) : null
          }
          draftOpen={draftOpen}
          kind={CHARACTER_PICK_BAN_KIND}
          selectedItemId={room.isSideStep ? room.selectedSide : room.selectedItemId}
          selectedItemName={
            room.isSideStep
              ? room.selectedSide != null
                ? (room.sideLabels[room.selectedSide] ?? `#${room.selectedSide}`)
                : null
              : room.selectedItemName
          }
          selectedItem={!room.isSideStep && room.selectedItemId != null ? heroesById[room.selectedItemId] : undefined}
          pending={room.acting || hostAct.isPending}
          forMember={room.actingMemberName}
          hint={pickHint}
          onConfirm={(itemId) => {
            if (room.captainAction != null) {
              room.confirm(itemId);
              return;
            }
            const teamId = state.acting_team_ids[0];
            if (hostAction != null && teamId != null) {
              hostAct.mutate({ encounter_team_id: teamId, item_id: itemId, action: hostAction });
            }
          }}
          onCancel={room.cancelSelection}
        />
      ) : (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("closed")}</p>
      )}

      <ElectOpenerDialog
        kind={CHARACTER_PICK_BAN_KIND}
        encounterId={encounterId}
        open={room.showElectOpener}
        seats={room.seats}
        queryKey={queryKey}
      />
    </div>
  );
}

const STEP_LABEL: Record<
  PickBanResolvedStep["action"],
  "ban" | "pick" | "protect" | "side" | "decider" | "assign"
> = {
  ban: "ban",
  pick: "pick",
  protect: "protect",
  side_pick: "side",
  decider: "decider",
  assign: "assign"
};

const STEP_ICON: Record<PickBanResolvedStep["action"], LucideIcon> = {
  ban: Ban,
  pick: Check,
  protect: Shield,
  side_pick: Flag,
  decider: Shuffle,
  assign: Users
};

/** Steps that land a hero in their slot; the others (a side, an assignment, a decider) show their icon. */
const HERO_STEP: Partial<Record<PickBanResolvedStep["action"], true>> = { ban: true, pick: true, protect: true };

/**
 * The room's order as a draft track: one slot per hero a step takes, in the colour of the team that takes it, runs
 * of the same action under one label. A slot shows the hero once it is chosen (a blind one only after the reveal,
 * a lock until then); the step in play is lifted and its empty slots pulse.
 */
function StepStrip({
  state,
  seats,
  heroesById,
  teamName
}: Readonly<{
  state: PickBanState;
  seats: readonly PickBanSeat[];
  heroesById: Record<number, PickBanItemLike | undefined>;
  teamName: (teamId: number) => string;
}>) {
  const t = useTranslations("mixes.arena.bans");
  const order = [...seats].sort((left, right) => left.slot - right.slot).map((seat) => seat.id);
  const current = state.is_complete ? state.sequence.length : (state.current_step_index ?? -1);
  const runs = state.sequence.reduce<PickBanResolvedStep[][]>((acc, step) => {
    const last = acc.at(-1);
    if (last != null && last[0].action === step.action) last.push(step);
    else acc.push([step]);
    return acc;
  }, []);

  const stepItem = (step: PickBanResolvedStep) => {
    const now = step.index === current;
    const past = step.index < current;
    const label = STEP_LABEL[step.action];
    const Icon = STEP_ICON[step.action];
    const rows = stepSubmissions(state.submissions, step.index).filter((row) => row.state !== "draft");
    // `[null]` is the engine's own step, `[]` a side actor still unresolved: one neutral slot either way.
    const actors: (number | null)[] = step.actors.length > 0 ? step.actors : [null];
    const who = actors.flatMap((actor) => {
      const index = actor == null ? -1 : order.indexOf(actor);
      return index < 0 ? [] : [String.fromCharCode(65 + index)];
    });

    const slots = actors.flatMap((teamId) => {
      const index = teamId == null ? -1 : order.indexOf(teamId);
      const accent = index < 0 ? null : teamAccent(index);
      const players = teamId == null ? 0 : (step.member_seats?.filter(([team]) => team === teamId).length ?? 0);
      const count = teamId == null || !HERO_STEP[step.action] ? 1 : Math.max(players, 1) * step.count;
      const heroes = HERO_STEP[step.action]
        ? rows
            .filter((row) => row.encounter_team_id === teamId)
            .flatMap((row) => row.items.map((item) => item.item_id))
        : [];
      const hidden = now && step.blind && teamId != null ? (state.step_progress?.[teamId]?.filled ?? 0) : 0;
      const actorName = teamId != null ? teamName(teamId) : "";

      return Array.from({ length: count }, (_, slot) => {
        const heroId = heroes[slot] ?? null;
        const heroName = heroId != null ? (heroesById[heroId]?.name ?? `#${heroId}`) : null;
        const locked = heroId == null && slot < hidden;
        const answered = !HERO_STEP[step.action] && rows.some((row) => row.encounter_team_id === teamId);
        const filled = heroId != null || locked || answered || past;
        const name = [actorName, t(`step.${label}`), heroName ?? (locked ? t("hidden") : null)]
          .filter(Boolean)
          .join(" · ");
        return (
          <span
            key={`${teamId ?? "system"}:${slot}`}
            role="img"
            aria-label={name}
            title={name}
            className={cn(
              "relative grid size-9 shrink-0 place-items-center overflow-hidden rounded-lg border-2 transition-colors",
              accent == null
                ? "border-[color:var(--aqt-border)]"
                : filled || now
                  ? accent.border
                  : accent.crestBorder,
              !filled && !now ? "border-dashed" : null,
              now && !filled ? cn(accent?.crestPanel, "animate-pulse motion-reduce:animate-none") : null
            )}
          >
            {heroId != null ? (
              <>
                <PickBanItemThumb
                  kind={CHARACTER_PICK_BAN_KIND}
                  item={heroesById[heroId]}
                  name={heroName ?? ""}
                  size={32}
                  muted={step.action === "ban"}
                />
                {step.action === "ban" ? (
                  <Ban aria-hidden className="absolute size-6 text-[color:var(--aqt-rose)]" strokeWidth={1.75} />
                ) : step.action === "protect" ? (
                  <Shield
                    aria-hidden
                    className="absolute bottom-0.5 right-0.5 size-3 text-[color:var(--aqt-amber)]"
                  />
                ) : null}
              </>
            ) : locked ? (
              <Lock aria-hidden className="size-3.5 text-[color:var(--aqt-fg-muted)]" />
            ) : (
              <Icon
                aria-hidden
                className={cn(
                  "size-3.5",
                  now ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-faint)]",
                  step.action === "ban" && now ? "text-[color:var(--aqt-rose)]" : null
                )}
              />
            )}
          </span>
        );
      });
    });

    return (
      <li
        key={`${step.round}:${step.index}`}
        aria-current={now ? "step" : undefined}
        className={cn(
          "flex gap-1 rounded-xl p-1 transition-colors",
          now ? "bg-[color:var(--aqt-card-2)] ring-1 ring-[color:var(--aqt-fg-faint)]/40" : null
        )}
      >
        <span className="sr-only">
          {[
            t(`step.${label}`),
            who.join("·"),
            step.member === "each" ? t("everyone") : "",
            step.count > 1 ? `×${step.count}` : ""
          ]
            .filter(Boolean)
            .join(" ")}
        </span>
        {slots}
      </li>
    );
  };

  return (
    <ol aria-label={t("steps")} className="flex flex-wrap gap-x-4 gap-y-3">
      {runs.map((run) => (
        <li key={`${run[0].round}:${run[0].index}`} className="flex flex-col gap-1">
          <span aria-hidden className={eyebrowClass("dim")}>
            {t(`phase.${STEP_LABEL[run[0].action]}`)}
          </span>
          <ol className="flex flex-wrap items-center gap-0.5">{run.map(stepItem)}</ol>
        </li>
      ))}
    </ol>
  );
}

/**
 * What the room waits for, above the pool: the viewer's own turn in the action's colour (rose for a ban) with what
 * to do, else whose turn it is in that team's colour; the step's clock and place in the order beside it.
 */
function TurnBanner({
  state,
  seats,
  mine,
  teamName
}: Readonly<{
  state: PickBanState;
  seats: readonly PickBanSeat[];
  mine: boolean;
  teamName: (teamId: number) => string;
}>) {
  const t = useTranslations("mixes.arena.bans");
  const tPickBan = useTranslations("pickBan.room");
  const step = state.current_step;
  const paused = state.session?.paused_at != null;
  if (step == null && !state.is_complete && !paused) return null;

  const ban = step?.action === "ban";
  const acting = state.acting_team_ids;
  const order = [...seats].sort((left, right) => left.slot - right.slot).map((seat) => seat.id);
  const turnIndex = acting.length === 1 ? order.indexOf(acting[0]) : -1;
  const pickers =
    step?.member != null && step.member !== "any"
      ? state.acting_member_ids.map((id) => memberName(state.members, id))
      : [];
  const headline = paused
    ? tPickBan("pausedBanner")
    : state.is_complete || step == null
      ? tPickBan("completedBanner")
      : mine
        ? t(`yours.${STEP_LABEL[step.action]}`)
        : step.actors.every((actor) => actor == null)
          ? tPickBan(`step.system.${step.action}`)
          : pickers.length > 0
            ? tPickBan("turnMembers", { names: pickers.join(", ") })
            : acting.length === 0
              ? tPickBan("turnRevealing")
              : acting.length > 1
                ? tPickBan(`step.both.${step.action}`)
                : tPickBan(`step.side.${step.action}`, { team: teamName(acting[0]) });
  const hint =
    !mine || step == null
      ? null
      : [
          t(
            `yoursHint.${step.action === "side_pick" ? "side" : step.action === "assign" ? "assign" : "hero"}`
          ),
          step.blind ? t("blindHint") : null
        ]
          .filter(Boolean)
          .join(". ");
  const deadline = stepDeadlineMs(state);
  const live = step != null && !state.is_complete && !paused;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-3.5 py-3",
        !mine
          ? "border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40"
          : ban
            ? "border-[color:var(--aqt-rose)]/60 bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)]"
            : "border-[color:var(--aqt-teal)]/60 bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)]"
      )}
    >
      {paused ? (
        <Pause aria-hidden className="size-5 shrink-0 text-[color:var(--aqt-amber)]" />
      ) : mine ? (
        <span aria-hidden className="relative flex size-3 shrink-0">
          <span
            className={cn(
              "absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:animate-none",
              ban ? "bg-[color:var(--aqt-rose)]" : "bg-[color:var(--aqt-teal)]"
            )}
          />
          <span
            className={cn(
              "relative inline-flex size-3 rounded-full",
              ban ? "bg-[color:var(--aqt-rose)]" : "bg-[color:var(--aqt-teal)]"
            )}
          />
        </span>
      ) : live && turnIndex >= 0 ? (
        <span aria-hidden className={cn("h-9 w-1 shrink-0 rounded-full", teamAccent(turnIndex).bar)} />
      ) : null}
      <div className="min-w-0 flex-1">
        <p
          aria-live="polite"
          className={cn(
            "font-display font-semibold",
            mine ? "text-title" : "text-ui text-[color:var(--aqt-fg)]",
            mine ? (ban ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-teal)]") : null
          )}
        >
          {headline}
          {mine && step != null && step.count > 1 ? (
            <span className="ml-1.5 tabular-nums opacity-80">{tPickBan("step.count", { n: step.count })}</span>
          ) : null}
        </p>
        {hint != null ? <p className="text-caption text-[color:var(--aqt-fg-muted)]">{hint}</p> : null}
      </div>
      {live ? (
        <div className="flex shrink-0 flex-col items-end gap-0.5">
          {deadline != null && step.timer_seconds != null ? (
            <PickBanCountdown deadline={deadline} totalSeconds={step.timer_seconds} compact />
          ) : null}
          <span className="text-label tabular-nums text-[color:var(--aqt-fg-faint)]">
            {t("stepOf", { n: step.index + 1, total: state.sequence.length })}
          </span>
        </div>
      ) : null}
    </div>
  );
}
