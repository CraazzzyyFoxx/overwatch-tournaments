"use client";

import { useState } from "react";
import { RotateCcw, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import pickBanService from "@/services/pickBan.service";
import type {
  PickBanAction,
  PickBanGame,
  PickBanKind,
  PickBanState
} from "@/types/tournament.types";

import type { PickBanSide } from "@/components/pick-ban/pick-ban-model";
import { Spinner } from "@/components/ui/spinner";

interface PregameAdminControlsProps {
  kind: PickBanKind;
  encounterId: number;
  state: PickBanState;
  allowProtect: boolean;
  selectedItemId: number | null;
  selectedItemName: string | null;
  onMutated: () => void;
}

/**
 * Workspace-admin overrides: reset the whole pick-ban session (drop +
 * re-create with seeds re-resolved), perform a step on behalf of either side,
 * and correct the accepted result of a game that is already confirmed or stuck
 * in a dispute — the one command allowed to overwrite a confirmed score, and
 * the only way a disputed position ever clears.
 */
export function PregameAdminControls({
  kind,
  encounterId,
  state,
  allowProtect,
  selectedItemId,
  selectedItemName,
  onMutated
}: Readonly<PregameAdminControlsProps>) {
  const t = useTranslations("pickBan.room");
  const defaultSide: PickBanSide = state.turn_side ?? "home";
  const defaultAction: PickBanAction =
    state.expected_action === "pick"
      ? "pick"
      : state.expected_action === "protect"
        ? "protect"
        : "ban";
  // The override is stored WITH the step it was made for, so a new step
  // automatically falls back to what the sequence expects.
  const step = state.current_step_index;
  const [resetOpen, setResetOpen] = useState(false);
  const [override, setOverride] = useState<{
    step: number | null;
    side: PickBanSide;
    action: PickBanAction;
  } | null>(null);
  const isOverridden = override?.step === step;
  const side = isOverridden ? override.side : defaultSide;
  const action = isOverridden ? override.action : defaultAction;
  const setSide = (next: PickBanSide) => setOverride({ step, side: next, action });
  const setAction = (next: PickBanAction) => setOverride({ step, side, action: next });

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

  const electMutation = useMutation({
    mutationFn: (first_side: PickBanSide) =>
      adminService.adminPickBanElectOpener(encounterId, { kind, first_side }),
    onSuccess: onMutated,
    onError: (error) => notify.apiError(error, { title: t("admin.electFailed") })
  });

  // `result_loser_choice` is the one rotation whose next round cannot open
  // without a human naming its opener. When the losing captain is unreachable
  // the room has nothing to click, so the organizer names it for them.
  const awaitingChoice = state.session?.awaiting_choice === true;

  const canAct = state.session?.status === "active" && !state.is_complete && selectedItemId != null;
  const pending = resetMutation.isPending || actMutation.isPending || electMutation.isPending;

  const actionOptions: { value: PickBanAction; label: string }[] = [
    { value: "ban", label: t("action.ban") },
    { value: "pick", label: t("action.pick") },
    ...(allowProtect ? [{ value: "protect" as const, label: t("action.protect") }] : [])
  ];
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
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        {state.session?.status === "active" && !state.is_complete ? (
          <>
            <ChoiceGroup
              label={t("admin.sideLabel")}
              options={[
                { value: "home", label: t("side.home") },
                { value: "away", label: t("side.away") }
              ]}
              value={side}
              onChange={setSide}
            />
            <ChoiceGroup
              label={t("admin.actionLabel")}
              options={actionOptions}
              value={action}
              onChange={setAction}
            />
            <Button
              size="sm"
              disabled={!canAct || pending}
              onClick={() => {
                if (selectedItemId == null) return;
                actMutation.mutate({ side, item_id: selectedItemId, action });
              }}
            >
              {actMutation.isPending ? (
                <Spinner className="mr-2" />
              ) : null}
              {t("admin.confirm")}
              {selectedItemName ? `: ${selectedItemName}` : ""}
            </Button>
            {selectedItemId == null ? (
              <span className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("admin.selectItemFirst")}
              </span>
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
                  {electMutation.isPending ? (
                    <Spinner className="mr-2" />
                  ) : null}
                  {t(value === "home" ? "side.home" : "side.away")}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        <Button
          size="sm"
          variant="destructive"
          disabled={pending}
          className="ml-auto"
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
