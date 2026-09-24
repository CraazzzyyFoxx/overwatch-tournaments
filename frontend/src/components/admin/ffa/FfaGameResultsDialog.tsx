"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Input } from "@/components/ui/input";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type { FfaGameResultsInput, FfaLobby } from "@/types/ffa.types";

/**
 * Turn any thrown value into the sentence for the rejection it carries.
 *
 * The FFA writes answer a machine code (`ffa_result_invalid_placement`,
 * `ffa_games_below_played`, …) with an English `msg` meant for a log. The
 * catalogue is the lookup rather than a second copy of the code list here: a
 * code with a message gets that message, anything else falls back to whatever
 * the server said, so a code added backend-side degrades instead of breaking.
 */
export function useFfaErrorMessage(): (error: unknown) => string {
  const t = useTranslations();
  return (error: unknown) => {
    if (error instanceof ApiError) {
      for (const detail of error.details) {
        // Built from a server-supplied code, so it is none of next-intl's
        // statically known literals; every `ffa.errors.*` message takes no
        // arguments, so one of them stands in for the shape of all of them.
        const key = `ffa.errors.${detail.code}` as "ffa.errors.ffa_reason_required";
        if (t.has(key)) return t(key);
      }
    }
    return getApiErrorMessage(error);
  };
}

export interface FfaGameResultsDialogProps {
  lobby: FfaLobby;
  /** Which game of the series is being entered, 1-based. */
  position: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * One game of one lobby, entered as a line per participant.
 *
 * A lobby is scored as a whole — the server rejects a payload that skips a
 * seated team (`ffa_result_missing_team`) — so the form is every row of the
 * lobby, and an untouched row still leaves as a line scoring zero rather than
 * as no line at all.
 *
 * Whether a place is required is the stage's formula, not a preference: with
 * `placement_points` the server demands a permutation of 1..N, and without it
 * the places are derived from the scores, which is why they are optional there.
 *
 * Mount with a `key` per game: the fields are seeded once from what the lobby
 * already records for that position, so a correction starts from the numbers
 * being corrected instead of from an empty form.
 */
export function FfaGameResultsDialog({
  lobby,
  position,
  open,
  onOpenChange
}: Readonly<FfaGameResultsDialogProps>) {
  const queryClient = useQueryClient();
  const describeError = useFfaErrorMessage();
  const t = useTranslations();

  const rows = [...lobby.rows].sort((left, right) => left.slot - right.slot);
  const cells = new Map(
    rows.map((row) => [row.team_id, row.games.find((game) => game.position === position)])
  );

  // A game somebody has already played: entering it again is a CORRECTION, and
  // the server refuses one of those without a reason.
  const isCorrection = [...cells.values()].some((cell) => cell?.state != null);
  const paysForPlacement = lobby.rules.placement_points.length > 0;
  const scoreLabel = lobby.rules.score_label?.trim() || "Score";

  const [draft, setDraft] = useState<Record<number, { placement: string; score: string }>>(() =>
    Object.fromEntries(
      rows.map((row) => [
        row.team_id,
        {
          placement: cells.get(row.team_id)?.placement?.toString() ?? "",
          score: cells.get(row.team_id)?.score?.toString() ?? ""
        }
      ])
    )
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Set by a refused submit, so an untouched form is not painted red on open.
  const [blanksFlagged, setBlanksFlagged] = useState(false);

  const mutation = useMutation({
    mutationFn: (input: FfaGameResultsInput) =>
      ffaService.setGameResults(lobby.encounter_id, position, input),
    onSuccess: () => {
      notify.success(`Game ${position} saved`);
      // One prefix covers the stage list, this lobby and the public table: a
      // game moves the whole group's standings, not one row.
      void queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.ffaAll(lobby.tournament_id)
      });
      onOpenChange(false);
    },
    // The global mutation cache toasts every rejection; this one is reported
    // inside the dialog, next to the fields it is about.
    meta: { suppressErrorToast: true },
    onError: (failure: unknown) => setError(describeError(failure))
  });

  const setField = (teamId: number, field: "placement" | "score", value: string) =>
    setDraft((current) => ({ ...current, [teamId]: { ...current[teamId], [field]: value } }));

  const blanks = rows.filter((row) => draft[row.team_id].score.trim() === "");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = reason.trim();
    if (isCorrection && !trimmed) {
      // The server refuses this with `ffa_reason_required`. Spending the round
      // trip to learn it would only cost the organizer the numbers just typed.
      setBlanksFlagged(false);
      setError(t("ffa.errors.ffa_reason_required"));
      return;
    }
    if (blanks.length > 0) {
      // A blank is NOT a zero. Sending it as one would record "played, scored
      // nothing" for a team the organizer simply had not got to yet — and the
      // server's own `ffa_result_missing_team` guard can never catch that,
      // because the line was there.
      setBlanksFlagged(true);
      setError(
        `Every team needs a ${scoreLabel.toLowerCase()} — type 0 for a team that scored nothing.`
      );
      return;
    }
    setBlanksFlagged(false);
    setError(null);
    mutation.mutate({
      results: rows.map((row) => {
        const entry = draft[row.team_id];
        return {
          team_id: row.team_id,
          placement: entry.placement.trim() === "" ? null : Number(entry.placement),
          score: Number(entry.score)
        };
      }),
      reason: trimmed || null
    });
  };

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={isCorrection ? `Correct game ${position}` : `Enter game ${position}`}
      description={`${lobby.name} · ${rows.length} teams · game ${position} of ${lobby.best_of}`}
      onSubmit={handleSubmit}
      submitLabel={isCorrection ? "Save correction" : "Save game"}
      isSubmitting={mutation.isPending}
      errorMessage={error ?? undefined}
    >
      <div className="grid grid-cols-[1fr_5rem_6rem] items-center gap-2">
        <span className={EYEBROW_CLASS}>Team</span>
        <span className={EYEBROW_CLASS}>{paysForPlacement ? "Place" : "Place (optional)"}</span>
        <span className={EYEBROW_CLASS}>{scoreLabel}</span>
        {rows.map((row) => (
          <FieldRow
            key={row.team_id}
            name={row.team_name}
            placement={draft[row.team_id].placement}
            score={draft[row.team_id].score}
            scoreLabel={scoreLabel}
            scoreMissing={blanksFlagged && draft[row.team_id].score.trim() === ""}
            onPlacement={(value) => setField(row.team_id, "placement", value)}
            onScore={(value) => setField(row.team_id, "score", value)}
          />
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        {paysForPlacement
          ? `Places run 1 to ${rows.length}, each taken exactly once — this stage pays for them.`
          : "Leave the places empty to derive them from the scores; teams on the same score share a place."}
      </p>

      {isCorrection ? (
        <div className="space-y-1">
          <label className={EYEBROW_CLASS} htmlFor="ffa-correction-reason">
            Reason
          </label>
          <Input
            id="ffa-correction-reason"
            aria-label="Reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why this game is being re-entered"
          />
          <p className="text-xs text-muted-foreground">
            This game has been played. The reason is recorded in the lobby’s audit trail.
          </p>
        </div>
      ) : null}
    </EntityFormDialog>
  );
}

function FieldRow({
  name,
  placement,
  score,
  scoreLabel,
  scoreMissing,
  onPlacement,
  onScore
}: Readonly<{
  name: string;
  placement: string;
  score: string;
  scoreLabel: string;
  scoreMissing: boolean;
  onPlacement: (value: string) => void;
  onScore: (value: string) => void;
}>) {
  return (
    <>
      <span className="truncate text-sm text-foreground">{name}</span>
      <Input
        type="number"
        min={1}
        inputMode="numeric"
        aria-label={`Place for ${name}`}
        value={placement}
        onChange={(event) => onPlacement(event.target.value)}
      />
      <Input
        type="number"
        min={0}
        inputMode="numeric"
        aria-label={`${scoreLabel} for ${name}`}
        aria-invalid={scoreMissing || undefined}
        value={score}
        onChange={(event) => onScore(event.target.value)}
      />
    </>
  );
}
