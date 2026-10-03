"use client";

import { useState } from "react";
import { Ban, Pause, Play, RotateCcw, ShieldCheck, Timer, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

import type { PickBanSide } from "@/components/pick-ban/pick-ban-model";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { Spinner } from "@/components/ui/spinner";

import type { PickBanAdminSlot } from "./PickBanPanel";

interface PregameAdminControlsProps {
  kind: PickBanKind;
  encounterId: number;
  state: PickBanState;
  selectedItemId: number | null;
  selectedItemName: string | null;
  /** This kind's catalog, to name the tiles an organizer clicked. */
  itemsById: Record<number, PickBanItemLike | undefined>;
  /**
   * The blind draft the board on screen is building for an absent captain —
   * null when no pool is on screen for this kind, or no blind step is open.
   */
  blind: PickBanAdminSlot["blind"];
  sideNameOf: (side: PickBanSide) => string;
  /** Series length and the wins already confirmed, for the technical loss's
   * default score — neither is carried by a pick-ban state. */
  bestOf: number;
  seriesWins: { home: number; away: number } | null;
  onMutated: () => void;
  /**
   * Which pick-ban kind these controls act on, when the room has more than
   * one session to offer. Lives in the title row because that is the only
   * place a switch reads as "this panel's scope" rather than another command.
   */
  kindSwitch?: React.ReactNode;
}

/** Enough to cover a reconnect, a short break and a long one. */
const EXTEND_CHOICES = [30, 60, 120] as const;

/**
 * The score a technical loss defaults to — the backend's own rule, mirrored
 * here so the dialog opens on the number it would apply and the organizer only
 * types when they disagree.
 *
 * The winner takes the series (at least the wins it needs), the forfeiting
 * side keeps the maps it actually won, capped one short of winning.
 */
function technicalLossScore(
  bestOf: number,
  wins: { home: number; away: number } | null,
  loserSide: PickBanSide
): { home: number; away: number } {
  const need = Math.floor(bestOf / 2) + 1;
  const winnerSide = loserSide === "home" ? "away" : "home";
  const score = {
    [winnerSide]: Math.max(wins?.[winnerSide] ?? 0, need),
    [loserSide]: Math.min(wins?.[loserSide] ?? 0, Math.max(need - 1, 0))
  } as { home: number; away: number };
  return score;
}

/**
 * Workspace-admin overrides: reset the whole pick-ban session (drop +
 * re-create with seeds re-resolved), act or submit a draft on behalf of either
 * side, reopen a revealed step, and correct the accepted result of a game that
 * is already confirmed or stuck in a dispute — the one command allowed to
 * overwrite a confirmed score, and the only way a disputed position ever
 * clears.
 *
 * Plus the commands that act on the session as a whole rather than on a step:
 * hold the clock (pause), hand the side on the clock more time, cancel the
 * session for good, and end the whole encounter against one side.
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
  blind,
  sideNameOf,
  bestOf,
  seriesWins,
  onMutated,
  kindSwitch
}: Readonly<PregameAdminControlsProps>) {
  const t = useTranslations("pickBan.room");
  const step = state.current_step;
  // The step names the action; the override only chooses WHOSE turn is being
  // taken, and it is stored with the step it was made for so the next step
  // falls back to whoever is actually on the clock.
  const action: PickBanAction =
    step?.action === "pick" ? "pick" : step?.action === "protect" ? "protect" : "ban";
  const defaultSide: PickBanSide = state.acting_sides[0] ?? "home";
  const [resetOpen, setResetOpen] = useState(false);
  const [override, setOverride] = useState<{ step: number | null; side: PickBanSide } | null>(null);
  const side = override?.step === (step?.index ?? null) ? override.side : defaultSide;
  const [lockSubmission, setLockSubmission] = useState(true);
  const itemName = (itemId: number) =>
    itemsById[itemId]?.name ?? t(`${kind}.itemNumber`, { id: itemId });
  // A per-player step names an OPPONENT of the side being acted for.
  const targetRoster = state.targets?.[side === "home" ? "away" : "home"] ?? [];

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
    mutationFn: (input: { side: PickBanSide; item_id: number; action: PickBanAction }) =>
      adminService.adminPickBanAct(encounterId, { kind, ...input }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.actFailed") })
  });

  const submitMutation = useMutation({
    mutationFn: (input: { side: PickBanSide; items: PickBanSubmissionItem[]; lock: boolean }) =>
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
    mutationFn: (first_side: PickBanSide) =>
      adminService.adminPickBanElectOpener(encounterId, { kind, first_side }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.electFailed") })
  });

  const queryClient = useQueryClient();
  const paused = state.session?.paused_at != null;
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [lossOpen, setLossOpen] = useState(false);
  const [loserSide, setLoserSide] = useState<PickBanSide>("away");
  const [lossReason, setLossReason] = useState("");
  // Null = "whatever the default rule says for the side currently selected";
  // a value is the organizer having overridden it by hand.
  const [lossScore, setLossScore] = useState<{ home: number; away: number } | null>(null);
  const lossDefault = technicalLossScore(bestOf, seriesWins, loserSide);
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
        loser_side: loserSide,
        home_score: lossScoreShown.home,
        away_score: lossScoreShown.away,
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
  const correctable = (state.games ?? []).filter(
    (game) => game.state === "confirmed" || game.state === "disputed"
  );

  return (
    <section className="rounded-xl border border-dashed border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[color:var(--aqt-amber)]" aria-hidden />
        <h2 className="text-sm font-semibold">{t("admin.title")}</h2>
        {kindSwitch != null ? <div className="ml-auto">{kindSwitch}</div> : null}
      </div>

      {/* A completed or cancelled session has no step to act on and no opener
          to name, so this row -- and the divider under it -- would be empty. */}
      {active || awaitingChoice ? (
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          {active ? (
            <>
              <ChoiceGroup
                label={t("admin.sideLabel")}
                options={[
                  { value: "home", label: t("side.home") },
                  { value: "away", label: t("side.away") }
                ]}
                value={side}
                onChange={(next) => {
                  setOverride({ step: step?.index ?? null, side: next });
                  // The draft so far was built for the other side: on a targeted
                  // step its players belong to the wrong roster entirely.
                  blind?.clear();
                }}
              />
              <div className="flex flex-col gap-1">
                <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                  {t("admin.actionLabel")}
                </span>
                <span className="text-sm font-medium capitalize">{t(`action.${action}`)}</span>
              </div>
              {step?.blind ? (
                <>
                  {step.target != null ? (
                    <ChoiceGroup
                      label={t("admin.submitTargetLabel")}
                      options={targetRoster.map((player) => ({
                        value: String(player.player_id),
                        label: player.name
                      }))}
                      value={String(blind?.targetPlayerId ?? "")}
                      onChange={(value) => blind?.setTargetPlayerId(Number(value))}
                    />
                  ) : null}
                  <div className="flex flex-col gap-1">
                    <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                      {t("admin.submitLabel")}
                    </span>
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
                                  )?.name ?? `#${item.target_player_id}`
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
                      submitMutation.mutate({ side, items: blind.items, lock: lockSubmission });
                    }}
                  >
                    {submitMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {t("admin.submitConfirm")}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    disabled={!canAct || pending}
                    onClick={() => {
                      if (selectedItemId == null) return;
                      actMutation.mutate({ side, item_id: selectedItemId, action });
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
              {state.dispute.step_index != null ? (
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
            </>
          ) : null}

          {awaitingChoice ? (
            <div className="flex flex-col gap-1">
              <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("admin.electLabel")}
              </span>
              <div className="flex gap-1">
                {(["home", "away"] as const).map((value) => (
                  <Button
                    key={value}
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    onClick={() => electMutation.mutate(value)}
                  >
                    {electMutation.isPending ? <Spinner className="mr-2" /> : null}
                    {t(value === "home" ? "side.home" : "side.away")}
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
          (active || awaitingChoice) &&
            "mt-4 border-t border-dashed border-[color:var(--aqt-amber)]/35 pt-3"
        )}
      >
        <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
          {t("admin.sessionLabel")}
        </span>
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
                  options={[
                    { value: "home" as PickBanSide, label: sideNameOf("home") },
                    { value: "away" as PickBanSide, label: sideNameOf("away") }
                  ]}
                  value={loserSide}
                  onChange={(next) => {
                    setLoserSide(next);
                    // The default score is read off who forfeits, so a hand
                    // edit made for the other side must not survive the switch.
                    setLossScore(null);
                  }}
                />
                <span className="flex items-end gap-2">
                  <NumberInput
                    min={0}
                    integer
                    className="w-16"
                    aria-label={t("admin.correctScore", { team: sideNameOf("home") })}
                    value={lossScoreShown.home}
                    onValueChange={(value) => setLossScore({ ...lossScoreShown, home: value ?? 0 })}
                  />
                  <NumberInput
                    min={0}
                    integer
                    className="w-16"
                    aria-label={t("admin.correctScore", { team: sideNameOf("away") })}
                    value={lossScoreShown.away}
                    onValueChange={(value) => setLossScore({ ...lossScoreShown, away: value ?? 0 })}
                  />
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
            lossScoreShown[loserSide] >= lossScoreShown[loserSide === "home" ? "away" : "home"]
          }
          onConfirm={() => technicalLossMutation.mutate()}
        />
      </div>

      {correctable.length > 0 ? (
        <div className="mt-4 flex flex-col gap-2 border-t border-dashed border-[color:var(--aqt-amber)]/35 pt-3">
          <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("admin.correctLabel")}
          </span>
          {correctable.map((game) => (
            <GameCorrection
              key={game.id}
              encounterId={encounterId}
              game={game}
              positionLabel={t("round.label", { n: game.position })}
              onMutated={onMutated}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/**
 * One game's correction: both scores as the SERIES sees them (home first, not
 * viewer-relative — the organizer is neither side) plus the reason the result
 * audit records. The reason is required because this row is the only writer
 * that can overwrite a confirmed score.
 */
function GameCorrection({
  encounterId,
  game,
  positionLabel,
  onMutated
}: Readonly<{
  encounterId: number;
  game: PickBanGame;
  positionLabel: string;
  onMutated: () => void;
}>) {
  const t = useTranslations("pickBan.room");
  const [homeScore, setHomeScore] = useState(game.accepted_home_score ?? 0);
  const [awayScore, setAwayScore] = useState(game.accepted_away_score ?? 0);
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      pickBanService.correctGameResult(encounterId, game.id, {
        home_score: homeScore,
        away_score: awayScore,
        reason
      }),
    onSuccess: () => {
      notify.success(t("admin.correctSuccess"));
      setReason("");
      onMutated();
    },
    onError: (error) => {
      // A later encounter of the bracket already started on the old result, so
      // the correction would silently invalidate a match in progress. Naming it
      // is the difference between "try again" and "go roll that back first".
      if (
        error instanceof ApiError &&
        error.details.some((detail) => detail.code === "downstream_started")
      ) {
        notify.error(t("admin.downstreamStarted"));
        return;
      }
      notify.apiError(error, { title: t("admin.correctFailed") });
    }
  });

  return (
    <div data-game-correction={game.id} className="flex flex-wrap items-end gap-2">
      <span className="min-w-[5rem] text-xs font-semibold">{positionLabel}</span>
      <NumberInput
        min={0}
        integer
        className="w-16"
        aria-label={t("admin.correctScore", { team: t("side.home") })}
        value={homeScore}
        onValueChange={(value) => setHomeScore(value ?? 0)}
      />
      <NumberInput
        min={0}
        integer
        className="w-16"
        aria-label={t("admin.correctScore", { team: t("side.away") })}
        value={awayScore}
        onValueChange={(value) => setAwayScore(value ?? 0)}
      />
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
      <span className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
        {label}
      </span>
      <div className="flex gap-1">
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={option.value === value ? "default" : "outline"}
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
