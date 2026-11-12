"use client";

import { useId, useState } from "react";
import { Ban, Pause, Play, RotateCcw, ShieldCheck, Timer, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import adminService from "@/services/admin.service";
import pickBanService from "@/services/pickBan.service";
import type {
  PickBanAction,
  PickBanGame,
  PickBanKind,
  PickBanState,
  PickBanSubmissionItem
} from "@/types/tournament.types";

import type { PickBanSeat } from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanSideChoice } from "@/components/pick-ban/PickBanSideChoice";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";

import { PregameAdminBox } from "./PregameAdminBox";
import type { PickBanAdminSlot } from "./usePickBanController";

interface PregameAdminControlsProps {
  kind: PickBanKind;
  encounterId: number;
  state: PickBanState;
  selectedItemId: number | null;
  selectedItemName: string | null;
  /** This kind's catalog, to name the tiles an organizer clicked. */
  itemsById: Record<number, PickBanItemLike | undefined>;
  /** The game's side labels in `state.sides` order: what a `side_pick` step chooses between. */
  sideLabels: string[];
  /**
   * The series' games, from the MAP state whatever kind these controls act on:
   * a hero-only room's hero state carries none, and its games still need correcting.
   */
  games: PickBanGame[] | undefined;
  /**
   * The blind draft the board on screen is building for an absent captain —
   * null when no pool is on screen for this kind, or no blind step is open.
   */
  blind: PickBanAdminSlot["blind"];
  /** The room's participations in slot order. */
  seats: PickBanSeat[];
  /** Series length and the wins already confirmed, for the technical loss's
   * default score — neither is carried by a pick-ban state. */
  bestOf: number;
  /** `EncounterTeam.id` (as a string) -> confirmed wins. */
  seriesWins: Record<string, number> | null;
  onMutated: () => void;
  /**
   * Which pick-ban kind these controls act on, when the room has more than
   * one session to offer. Lives in the title row because that is the only
   * place a switch reads as "this panel's scope" rather than another command.
   */
  kindSwitch?: React.ReactNode;
  /** Whether the technical loss is offered: a result, so only where this room writes results (a tournament). */
  technicalLoss?: boolean;
}

/** Enough to cover a reconnect, a short break and a long one. */
const EXTEND_CHOICES = [30, 60, 120] as const;

/**
 * The score a technical loss defaults to — the backend's own rule, mirrored
 * here so the dialog opens on the number it would apply and the organizer only
 * types when they disagree.
 *
 * The winner takes the series (at least the wins it needs), the forfeiting
 * team keeps the maps it actually won, capped one short of winning. Keyed by
 * `EncounterTeam.id`.
 */
function technicalLossScore(
  bestOf: number,
  wins: Record<string, number> | null,
  seats: PickBanSeat[],
  loserTeamId: number
): Record<number, number> {
  const need = Math.floor(bestOf / 2) + 1;
  const score: Record<number, number> = {};
  for (const seat of seats) {
    const won = wins?.[String(seat.id)] ?? 0;
    score[seat.id] = seat.id === loserTeamId ? Math.min(won, Math.max(need - 1, 0)) : Math.max(won, need);
  }
  return score;
}

/**
 * Whether the organizer's reopen lands on a settled side pick the series has not played on yet.
 *
 * Mirrors the route: it reopens the latest step anybody answered once every actor of it revealed
 * (`_reopenable`), and refuses a side step whose position carries a claim or a confirmed result
 * (`played_positions`, non-cancelled games only). A side step never disputes, so `state.dispute`
 * never names it. Games not loaded read as played: never offer a reopen that may be locked.
 */
function sideStepReopenable(state: PickBanState, games: PickBanGame[] | undefined): boolean {
  if (games == null || state.session == null || state.session.status === "cancelled") return false;
  // A later blind step's drafts are hidden from the organizer; its progress still says it was touched.
  const progress = Object.values(state.step_progress ?? {});
  if (progress.some((entry) => entry.locked || entry.filled > 0)) return false;
  const latest = Math.max(-1, ...state.submissions.map((row) => row.step_index));
  const step = state.sequence.find((candidate) => candidate.index === latest);
  if (step?.action !== "side_pick") return false;
  const settled = step.actors.every((actor) =>
    state.submissions.some(
      (row) =>
        row.step_index === step.index && row.encounter_team_id === actor && row.state === "revealed"
    )
  );
  const position = step.round ?? 1;
  const played = games.some(
    (game) =>
      game.position === position &&
      game.state !== "cancelled" &&
      (game.state === "confirmed" || game.claims.length > 0)
  );
  return settled && !played;
}

/**
 * Workspace-admin overrides: reset the whole pick-ban session (drop +
 * re-create with seeds re-resolved), act or submit a draft on behalf of either
 * team, reopen a revealed step, and correct the accepted result of a game that
 * is already confirmed or stuck in a dispute — the one command allowed to
 * overwrite a confirmed score, and the only way a disputed position ever
 * clears.
 *
 * Plus the commands that act on the session as a whole rather than on a step:
 * hold the clock (pause), hand the team on the clock more time, cancel the
 * session for good, and end the whole encounter against one team.
 *
 * Which action an override performs is NOT the organizer's choice any more: a
 * v2 step names its own action, so offering "ban / pick / protect" next to a
 * step that only accepts one of them was three buttons where two produced a
 * 400.
 */
export function PregameAdminControls({
  kind,
  encounterId,
  state,
  selectedItemId,
  selectedItemName,
  itemsById,
  sideLabels,
  games,
  blind,
  seats,
  bestOf,
  seriesWins,
  onMutated,
  kindSwitch,
  technicalLoss = true
}: Readonly<PregameAdminControlsProps>) {
  const t = useTranslations("pickBan.room");
  const step = state.current_step;
  // The step names the action; the override only chooses WHOSE turn is being
  // taken, and it is stored with the step it was made for so the next step
  // falls back to whoever is actually on the clock.
  const action: PickBanAction =
    step != null && step.action !== "decider" && step.action !== "assign" ? step.action : "ban";
  const sideStep = step?.action === "side_pick";
  const defaultTeamId = state.acting_team_ids[0] ?? seats[0]?.id ?? 0;
  const [resetOpen, setResetOpen] = useState(false);
  const [override, setOverride] = useState<{ step: number | null; teamId: number } | null>(null);
  const teamId = override?.step === (step?.index ?? null) ? override.teamId : defaultTeamId;
  // The side an organizer chose, by index, belongs to exactly one turn: this kind's session, this step and action
  // as it was (re)opened and its attempt, and the team it is chosen FOR. Any change discards it — a choice made
  // for one team must never be confirmed for the other, nor survive a reopen.
  const attempt =
    state.submissions.find((entry) => entry.step_index === step?.index && entry.encounter_team_id === teamId)
      ?.attempt ?? 0;
  const sideKey = [
    kind,
    state.session?.id,
    step?.index,
    step?.action,
    state.session?.current_step_started_at,
    attempt,
    teamId
  ].join(":");
  const [sidePick, setSidePick] = useState<{ key: string; index: number | null }>({ key: sideKey, index: null });
  if (sidePick.key !== sideKey) setSidePick({ key: sideKey, index: null });
  const sideIndex = sidePick.key === sideKey ? sidePick.index : null;
  const sideChoiceId = useId();
  const [lockSubmission, setLockSubmission] = useState(true);
  const itemName = (itemId: number) =>
    itemsById[itemId]?.name ?? t(`${kind}.itemNumber`, { id: itemId });
  // A per-player step names an OPPONENT of the team being acted for.
  const opponentId = seats.find((seat) => seat.id !== teamId)?.id;
  const targetRoster = (opponentId != null ? state.targets?.[opponentId] : undefined) ?? [];

  const resetMutation = useMutation({
    mutationFn: () => adminService.resetPickBanSession(encounterId, kind),
    onSuccess: () => {
      setResetOpen(false);
      notify.success(t("admin.resetSuccess"));
      onMutated();
    },
    onError: (error) => notify.apiError(error, { title: t("admin.resetFailed") })
  });

  const actMutation = useMutation({
    mutationFn: (input: { encounter_team_id: number; item_id: number; action: PickBanAction }) =>
      adminService.adminPickBanAct(encounterId, { kind, ...input }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.actFailed") })
  });

  const submitMutation = useMutation({
    mutationFn: (input: { encounter_team_id: number; items: PickBanSubmissionItem[]; lock: boolean }) =>
      adminService.adminPickBanSubmit(encounterId, { kind, ...input }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.submitFailed") })
  });

  const reopenMutation = useMutation({
    mutationFn: () => adminService.adminPickBanReopen(encounterId, kind),
    onSuccess: () => {
      notify.success(t("admin.reopenSuccess"));
      onMutated();
    },
    onError: (error) => notify.apiError(error, { title: t("admin.reopenFailed") })
  });

  const electMutation = useMutation({
    mutationFn: (first_team_id: number) =>
      adminService.adminPickBanElectOpener(encounterId, { kind, first_team_id }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.electFailed") })
  });

  const queryClient = useQueryClient();
  const paused = state.session?.paused_at != null;
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [lossOpen, setLossOpen] = useState(false);
  const [loserTeamId, setLoserTeamId] = useState<number>(seats[1]?.id ?? 0);
  const [lossReason, setLossReason] = useState("");
  // Null = "whatever the default rule says for the team currently selected";
  // a value is the organizer having overridden it by hand.
  const [lossScore, setLossScore] = useState<Record<number, number> | null>(null);
  const lossDefault = technicalLossScore(bestOf, seriesWins, seats, loserTeamId);
  const lossScoreShown = lossScore ?? lossDefault;

  const pauseMutation = useMutation({
    mutationFn: (next: boolean) =>
      adminService.adminPickBanPause(encounterId, { kind, paused: next }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.pauseFailed") })
  });

  const extendMutation = useMutation({
    mutationFn: (seconds: number) =>
      adminService.adminPickBanExtend(encounterId, { kind, seconds }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.extendFailed") })
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      adminService.adminPickBanCancel(encounterId, { kind, reason: cancelReason.trim() }),
    onSuccess: () => {
      setCancelOpen(false);
      setCancelReason("");
      notify.success(t("admin.cancelSuccess"));
      onMutated();
    },
    onError: (error) => notify.apiError(error, { title: t("admin.cancelFailed") })
  });

  const technicalLossMutation = useMutation({
    mutationFn: () =>
      adminService.adminTechnicalLoss(encounterId, {
        loser_team_id: loserTeamId,
        results: seats.map((seat) => ({
          encounter_team_id: seat.id,
          score: lossScoreShown[seat.id] ?? 0
        })),
        reason: lossReason.trim()
      }),
    onSuccess: () => {
      setLossOpen(false);
      setLossReason("");
      setLossScore(null);
      notify.success(t("admin.technicalLossSuccess"));
      onMutated();
      // This one writes the ENCOUNTER's result, not just a session, and the
      // room's own refetch may be scoped to the board the organizer is on.
      void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.detail(encounterId) });
    },
    onError: (error) => notify.apiError(error, { title: t("admin.technicalLossFailed") })
  });

  // `result_loser_choice` is the one rotation whose next round cannot open
  // without a human naming its opener. When the losing captain is unreachable
  // the room has nothing to click, so the organizer names it for them.
  const awaitingChoice = state.session?.awaiting_choice === true;

  const active = state.session?.status === "active" && !state.is_complete;
  // A side-only round's step list is done once its side is picked, so the side's reopen outlives `active`.
  const sideReopenable = sideStepReopenable(state, games);
  const reopenable = (active && state.dispute.step_index != null) || sideReopenable;
  const stepRow = active || awaitingChoice || sideReopenable;
  const canAct = active && selectedItemId != null;
  const pending =
    resetMutation.isPending ||
    actMutation.isPending ||
    electMutation.isPending ||
    submitMutation.isPending ||
    reopenMutation.isPending;
  // Only a settled position can be corrected: `planned`/`awaiting_result` have
  // no accepted score to overwrite, and a captain claim is the normal path
  // there. A dispute is here because it is the ONLY way one ever clears.
  const correctable = (games ?? []).filter(
    (game) => game.state === "confirmed" || game.state === "disputed"
  );

  return (
    <PregameAdminBox icon={ShieldCheck} title={t("admin.title")} aside={kindSwitch}>
      {/* A completed or cancelled session has no step to act on and no opener
          to name, so this row -- and the divider under it -- would be empty,
          unless a settled side pick can still be reopened. */}
      {stepRow ? (
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          {active ? (
            <>
              <ChoiceGroup
                label={t("admin.sideLabel")}
                options={seats.map((seat) => ({ value: String(seat.id), label: seat.name }))}
                value={String(teamId)}
                onChange={(next) => {
                  setOverride({ step: step?.index ?? null, teamId: Number(next) });
                  // The draft so far was built for the other team: on a targeted
                  // step its players belong to the wrong roster entirely.
                  blind?.clear();
                }}
              />
              <div className="flex flex-col gap-1">
                <Eyebrow>{t("admin.actionLabel")}</Eyebrow>
                <span className="text-sm font-medium capitalize">{t(`action.${action}`)}</span>
              </div>
              {step?.blind ? (
                <>
                  {step.target != null ? (
                    <ChoiceGroup
                      label={t("admin.submitTargetLabel")}
                      options={targetRoster.map((player) => ({
                        value: String(player.player_id),
                        label: player.display.name + (player.display.tag ?? "")
                      }))}
                      value={String(blind?.targetPlayerId ?? "")}
                      onChange={(value) => blind?.setTargetPlayerId(Number(value))}
                    />
                  ) : null}
                  <div className="flex flex-col gap-1">
                    <Eyebrow>{t("admin.submitLabel")}</Eyebrow>
                    {blind != null && blind.items.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-1">
                        {blind.items.map((item, index) => (
                          <Button
                            key={`${item.item_id}:${item.target_player_id ?? ""}`}
                            type="button"
                            size="sm"
                            variant="outline"
                            aria-label={t("admin.submitRemove", { item: itemName(item.item_id) })}
                            onClick={() => blind.removeAt(index)}
                          >
                            {item.target_player_id != null
                              ? `${itemName(item.item_id)} → ${
                                  targetRoster.find(
                                    (player) => player.player_id === item.target_player_id
                                  )?.display.name ?? `#${item.target_player_id}`
                                }`
                              : itemName(item.item_id)}
                            <span aria-hidden className="ml-2">
                              ×
                            </span>
                          </Button>
                        ))}
                      </div>
                    ) : (
                      <span className="max-w-64 text-xs text-[color:var(--aqt-fg-muted)]">
                        {t("admin.submitHint")}
                      </span>
                    )}
                  </div>
                  <label className="flex items-center gap-2 pb-1.5 text-xs">
                    <Checkbox
                      checked={lockSubmission}
                      onCheckedChange={(checked) => setLockSubmission(checked === true)}
                    />
                    {t("admin.submitLock")}
                  </label>
                  <Button
                    size="sm"
                    disabled={blind == null || blind.items.length === 0 || pending}
                    onClick={() => {
                      if (blind == null) return;
                      submitMutation.mutate({ encounter_team_id: teamId, items: blind.items, lock: lockSubmission });
                    }}
                  >
                    {submitMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {t("admin.submitConfirm")}
                  </Button>
                </>
              ) : sideStep ? (
                <>
                  <div className="flex flex-col gap-1">
                    <Eyebrow id={sideChoiceId}>{t("admin.sideChoiceLabel")}</Eyebrow>
                    <PickBanSideChoice
                      labelledBy={sideChoiceId}
                      labels={sideLabels}
                      value={sideIndex}
                      disabled={pending}
                      onChange={(index) => setSidePick({ key: sideKey, index })}
                    />
                  </div>
                  <Button
                    size="sm"
                    disabled={!active || sideIndex == null || pending}
                    onClick={() => {
                      if (sideIndex == null) return;
                      actMutation.mutate({ encounter_team_id: teamId, item_id: sideIndex, action: "side_pick" });
                    }}
                  >
                    {actMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {t("admin.confirm")}
                    {sideIndex != null ? `: ${sideLabels[sideIndex] ?? `#${sideIndex}`}` : ""}
                  </Button>
                </>
              ) : step?.member != null || step?.action === "assign" ? (
                <span className="max-w-64 text-xs text-[color:var(--aqt-fg-muted)]">{t("admin.actOnBoard")}</span>
              ) : (
                <>
                  <Button
                    size="sm"
                    disabled={!canAct || pending}
                    onClick={() => {
                      if (selectedItemId == null) return;
                      actMutation.mutate({ encounter_team_id: teamId, item_id: selectedItemId, action });
                    }}
                  >
                    {actMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {t("admin.confirm")}
                    {selectedItemName ? `: ${selectedItemName}` : ""}
                  </Button>
                  {selectedItemId == null ? (
                    <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                      {t("admin.selectItemFirst")}
                    </span>
                  ) : null}
                </>
              )}
            </>
          ) : null}

          {reopenable ? (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => reopenMutation.mutate()}
            >
              {reopenMutation.isPending ? (
                <Spinner className="mr-2" />
              ) : (
                <Undo2 className="mr-2 h-4 w-4" aria-hidden />
              )}
              {t("admin.reopen")}
            </Button>
          ) : null}

          {awaitingChoice ? (
            <div className="flex flex-col gap-1">
              <Eyebrow>{t("admin.electLabel")}</Eyebrow>
              <div className="flex gap-1">
                {seats.map((seat) => (
                  <Button
                    key={seat.id}
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    onClick={() => electMutation.mutate(seat.id)}
                  >
                    {electMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {seat.name}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Commands that act on the session (or the whole encounter) rather than
          on one step — kept off the step row so an organizer never reaches for
          "cancel" while aiming at "perform action". */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-2",
          stepRow &&
            "mt-4 border-t border-dashed border-[color:var(--aqt-amber)]/35 pt-3"
        )}
      >
        <Eyebrow>{t("admin.sessionLabel")}</Eyebrow>
        {active ? (
          <Button
            size="sm"
            variant="outline"
            disabled={pauseMutation.isPending}
            onClick={() => pauseMutation.mutate(!paused)}
          >
            {pauseMutation.isPending ? (
              <Spinner className="mr-2" />
            ) : paused ? (
              <Play className="mr-2 h-4 w-4" aria-hidden />
            ) : (
              <Pause className="mr-2 h-4 w-4" aria-hidden />
            )}
            {t(paused ? "admin.resume" : "admin.pause")}
          </Button>
        ) : null}
        {/* Nothing to extend without an open step that runs on a clock. */}
        {active && step?.timer_seconds != null ? (
          <div className="flex items-center gap-1">
            <Timer className="h-4 w-4 text-[color:var(--aqt-fg-faint)]" aria-hidden />
            {EXTEND_CHOICES.map((seconds) => (
              <Button
                key={seconds}
                size="sm"
                variant="outline"
                disabled={extendMutation.isPending}
                onClick={() => extendMutation.mutate(seconds)}
              >
                {t("admin.extendBy", { seconds })}
              </Button>
            ))}
          </div>
        ) : null}
        {state.session != null && state.session.status !== "cancelled" ? (
          <Button
            size="sm"
            variant="outline"
            className="text-danger"
            disabled={cancelMutation.isPending}
            onClick={() => setCancelOpen(true)}
          >
            {cancelMutation.isPending ? (
              <Spinner className="mr-2" />
            ) : (
              <Ban className="mr-2 h-4 w-4" aria-hidden />
            )}
            {t("admin.cancelSession")}
          </Button>
        ) : null}
        {/* A session-level command, like cancel: it drops this kind's session and
            re-creates it, so it belongs beside the other session commands, not
            at the end of the step row it never acts on. */}
        <Button
          size="sm"
          variant="outline"
          className="text-danger"
          disabled={pending}
          onClick={() => setResetOpen(true)}
        >
          {resetMutation.isPending ? (
            <Spinner className="mr-2" />
          ) : (
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
          )}
          {t("admin.reset")}
        </Button>
        <ConfirmDialog
          open={resetOpen}
          onOpenChange={setResetOpen}
          intent={{
            title: t("admin.resetConfirmTitle"),
            description: t("admin.resetConfirmHint"),
            confirmLabel: t("admin.resetConfirmAction"),
            tone: "danger"
          }}
          pending={resetMutation.isPending}
          onConfirm={() => resetMutation.mutate()}
        />
        <ConfirmDialog
          open={cancelOpen}
          onOpenChange={setCancelOpen}
          intent={{
            title: t("admin.cancelConfirmTitle"),
            description: (
              <span className="flex flex-col gap-2">
                <span>{t(kind === "hero" ? "admin.cancelHeroHint" : "admin.cancelMapHint")}</span>
                <span>{t("admin.cancelUndoHint")}</span>
                <Input
                  aria-label={t("admin.cancelReason")}
                  placeholder={t("admin.correctReasonPlaceholder")}
                  value={cancelReason}
                  onChange={(event) => setCancelReason(event.target.value)}
                />
              </span>
            ),
            confirmLabel: t("admin.cancelConfirmAction"),
            tone: "danger"
          }}
          pending={cancelMutation.isPending}
          confirmDisabled={cancelReason.trim() === ""}
          onConfirm={() => cancelMutation.mutate()}
        />
        {technicalLoss ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              className="ml-auto"
              disabled={technicalLossMutation.isPending}
              onClick={() => setLossOpen(true)}
            >
              {technicalLossMutation.isPending ? <Spinner className="mr-2" /> : null}
              {t("admin.technicalLoss")}
            </Button>
            <ConfirmDialog
              open={lossOpen}
              onOpenChange={setLossOpen}
              intent={{
                title: t("admin.technicalLossTitle"),
                description: (
                  <span className="flex flex-col gap-3">
                    <span>{t("admin.technicalLossHint")}</span>
                    <ChoiceGroup
                      label={t("admin.technicalLossSide")}
                      options={seats.map((seat) => ({ value: String(seat.id), label: seat.name }))}
                      value={String(loserTeamId)}
                      onChange={(next) => {
                        setLoserTeamId(Number(next));
                        // The default score is read off who forfeits, so a hand
                        // edit made for the other team must not survive the switch.
                        setLossScore(null);
                      }}
                    />
                    <span className="flex items-end gap-2">
                      {seats.map((seat) => (
                        <NumberInput
                          key={seat.id}
                          min={0}
                          integer
                          className="w-16"
                          aria-label={t("admin.correctScore", { team: seat.name })}
                          value={lossScoreShown[seat.id] ?? 0}
                          onValueChange={(value) =>
                            setLossScore({ ...lossScoreShown, [seat.id]: value ?? 0 })
                          }
                        />
                      ))}
                    </span>
                    <Input
                      aria-label={t("admin.technicalLossReason")}
                      placeholder={t("admin.correctReasonPlaceholder")}
                      value={lossReason}
                      onChange={(event) => setLossReason(event.target.value)}
                    />
                  </span>
                ),
                confirmLabel: t("admin.technicalLossAction"),
                tone: "danger"
              }}
              pending={technicalLossMutation.isPending}
              confirmDisabled={
                lossReason.trim() === "" ||
                seats.some(
                  (seat) =>
                    seat.id !== loserTeamId &&
                    (lossScoreShown[loserTeamId] ?? 0) >= (lossScoreShown[seat.id] ?? 0)
                )
              }
              onConfirm={() => technicalLossMutation.mutate()}
            />
          </>
        ) : null}
      </div>

      {correctable.length > 0 ? (
        <div className="mt-4 flex flex-col gap-2 border-t border-dashed border-[color:var(--aqt-amber)]/35 pt-3">
          <Eyebrow>{t("admin.correctLabel")}</Eyebrow>
          {correctable.map((game) => (
            <GameCorrection
              key={game.id}
              encounterId={encounterId}
              game={game}
              seats={seats}
              positionLabel={t("round.label", { n: game.position })}
              onMutated={onMutated}
            />
          ))}
        </div>
      ) : null}
    </PregameAdminBox>
  );
}

/**
 * One game's correction: both scores as the SERIES sees them (slot 1 first, not
 * viewer-relative — the organizer captains neither team) plus the reason the result
 * audit records. The reason is required because this row is the only writer
 * that can overwrite a confirmed score.
 */
function GameCorrection({
  encounterId,
  game,
  seats,
  positionLabel,
  onMutated
}: Readonly<{
  encounterId: number;
  game: PickBanGame;
  seats: PickBanSeat[];
  positionLabel: string;
  onMutated: () => void;
}>) {
  const t = useTranslations("pickBan.room");
  const [scores, setScores] = useState<Record<number, number>>(() =>
    Object.fromEntries(
      seats.map((seat) => [
        seat.id,
        game.results.find((line) => line.encounter_team_id === seat.id)?.score ?? 0
      ])
    )
  );
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      pickBanService.correctGameResult(encounterId, game.id, {
        results: seats.map((seat) => ({
          encounter_team_id: seat.id,
          score: scores[seat.id] ?? 0
        })),
        reason
      }),
    onSuccess: () => {
      notify.success(t("admin.correctSuccess"));
      setReason("");
      onMutated();
    },
    onError: (error) => {
      // The next game's pick-ban already ran on the old result (its round
      // opener came from it), so the correction would silently rewrite a
      // round in progress. Naming it is the difference between "try again"
      // and "undo that round first".
      if (
        error instanceof ApiError &&
        error.details.some((detail) => detail.code === "dependent_round_started")
      ) {
        notify.error(t("admin.dependentRoundStarted"));
        return;
      }
      notify.apiError(error, { title: t("admin.correctFailed") });
    }
  });

  return (
    <div data-game-correction={game.id} className="flex flex-wrap items-end gap-2">
      <span className="min-w-[5rem] text-xs font-semibold">{positionLabel}</span>
      {seats.map((seat) => (
        <NumberInput
          key={seat.id}
          min={0}
          integer
          className="w-16"
          aria-label={t("admin.correctScore", { team: seat.name })}
          value={scores[seat.id] ?? 0}
          onValueChange={(value) => setScores({ ...scores, [seat.id]: value ?? 0 })}
        />
      ))}
      <Input
        className="w-56"
        aria-label={t("admin.correctReason")}
        placeholder={t("admin.correctReasonPlaceholder")}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={reason.trim() === "" || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? <Spinner className="mr-2" /> : null}
        {t("admin.correctSubmit")}
      </Button>
    </div>
  );
}

function ChoiceGroup<TValue extends string>({
  label,
  options,
  value,
  onChange
}: Readonly<{
  label: string;
  options: { value: TValue; label: string }[];
  value: TValue;
  onChange: (value: TValue) => void;
}>) {
  return (
    <div className="flex flex-col gap-1">
      <Eyebrow>{label}</Eyebrow>
      <div className="flex gap-1">
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={option.value === value ? "accent" : "outline"}
            className={cn("capitalize", option.value === value ? "pointer-events-none" : null)}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
