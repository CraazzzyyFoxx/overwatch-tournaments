"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { ApiError, errorBodyFields, getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type {
  FfaColumn,
  FfaGameResultLineInput,
  FfaGameResultsInput,
  FfaLobby
} from "@/types/ffa.types";

/**
 * The FFA rejections a thrown value carries, richest form first.
 *
 * `ApiError.details` is the flattened human view and keeps only the code; the
 * structured entries the worker sent ride `body` (`errorBodyFields`), and that
 * is where a formula rejection keeps the things a message has to name — the
 * position inside the formula, and the name the parser stumbled over.
 */
export function ffaErrorEntries(
  error: unknown
): { code: string; offset?: number; name?: string }[] {
  if (!(error instanceof ApiError)) return [];
  const structured = errorBodyFields(error.body)
    .filter((entry) => typeof entry.code === "string")
    .map((entry) => ({
      code: entry.code as string,
      offset: typeof entry.offset === "number" ? entry.offset : undefined,
      name: typeof entry.name === "string" ? entry.name : undefined
    }));
  return structured.length > 0 ? structured : error.details.map((detail) => ({ code: detail.code }));
}

/**
 * Turn any thrown value into the sentence for the rejection it carries.
 *
 * The FFA writes and the FFA stage rules answer a machine code
 * (`ffa_result_invalid_placement`, `ffa_formula_unknown_name`, …) with an
 * English `msg` meant for a log. The catalogue is the lookup rather than a
 * second copy of the code list here: a code with a message gets that message,
 * anything else falls back to whatever the server said, so a code added
 * backend-side degrades instead of breaking.
 *
 * `offset` is reported 0-based and shown 1-based: the organizer counts the
 * characters of their formula from one.
 */
export function useFfaErrorMessage(): (error: unknown) => string {
  const t = useTranslations();
  return (error: unknown) => {
    for (const entry of ffaErrorEntries(error)) {
      // Built from a server-supplied code, so it is none of next-intl's
      // statically known literals; the key named here stands in for the shape of
      // all of them — no `ffa.errors.*` message reads more than these two
      // arguments, and one that reads neither ignores both.
      const key = `ffa.errors.${entry.code}` as "ffa.errors.ffa_reason_required";
      if (t.has(key)) {
        return t(key, { offset: (entry.offset ?? 0) + 1, name: entry.name ?? "" });
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

/** One row of the form. A `null` is "not entered yet", never a zero. */
type TeamDraft = { placement: number | null; stats: Record<string, number | null> };

/**
 * One game of one lobby, entered as a line per participant.
 *
 * A lobby is scored as a whole — the server rejects a payload that skips a
 * seated team (`ffa_result_missing_team`) — so the form is every row of the
 * lobby, and an untouched row still leaves as a line scoring zero rather than
 * as no line at all.
 *
 * Whether a place is required is the stage's formula, not a preference: a
 * formula that reads `place`/`place_pts` makes the server demand a permutation
 * of 1..N (`rules.requires_placement`), and a formula that does not lets the
 * server derive the places from the points, which is why they are optional
 * there. The columns are the organizer's too — every one of them, including the
 * ones a spectator never sees, because this form is where they are entered.
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
  const requiresPlacement = lobby.rules.requires_placement;
  // EVERY column, not the public ones: the dialog is mounted from a screen that
  // reads `getStageAdmin`, and a hidden column is a column the organizer still
  // has to type a number into.
  const columns = lobby.rules.columns;

  const [draft, setDraft] = useState<Record<number, TeamDraft>>(() =>
    Object.fromEntries(
      rows.map((row) => {
        const recorded = cells.get(row.team_id);
        return [
          row.team_id,
          {
            placement: recorded?.placement ?? null,
            // A correction starts from the numbers being corrected. A column
            // added after this game was played has no value here, and a blank
            // is the honest answer: nobody entered one.
            stats: Object.fromEntries(
              columns.map((column) => [column.key, recorded?.stats?.[column.key] ?? null])
            )
          }
        ];
      })
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

  const setPlacement = (teamId: number, value: number | null) =>
    setDraft((current) => ({ ...current, [teamId]: { ...current[teamId], placement: value } }));

  const setStat = (teamId: number, key: string, value: number | null) =>
    setDraft((current) => ({
      ...current,
      [teamId]: { ...current[teamId], stats: { ...current[teamId].stats, [key]: value } }
    }));

  /** The first column left blank anywhere, which is what holds the submit. */
  const blankColumn = columns.find((column) =>
    rows.some((row) => draft[row.team_id].stats[column.key] === null)
  );

  const results: FfaGameResultLineInput[] = rows.map((row) => ({
    team_id: row.team_id,
    placement: draft[row.team_id].placement,
    stats: Object.fromEntries(
      columns.map((column) => [column.key, draft[row.team_id].stats[column.key] ?? 0])
    )
  }));

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
    if (blankColumn) {
      // A blank is NOT a zero. Sending it as one would record "played, scored
      // nothing" for a team the organizer simply had not got to yet — and the
      // server's own `ffa_result_missing_stat` guard can never catch that,
      // because the key was there. A blank PLACE needs no guard here: it leaves
      // as `null` and the server answers `ffa_result_placement_required` when
      // the formula wants one, which is the one judgement it can make itself.
      setBlanksFlagged(true);
      // The label is whatever the organizer named the column ("Kills", "Deaths"),
      // so it is quoted as written rather than bent into a sentence around it.
      setError(
        `Enter ${blankColumn.label} for every team — type 0 for a team that scored nothing.`
      );
      return;
    }
    setBlanksFlagged(false);
    setError(null);
    mutation.mutate({ results, reason: trimmed || null });
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
      <div
        className="grid items-center gap-2 overflow-x-auto"
        // One column per stat, sized in the grid rather than in a class: the
        // stage decides how many there are, and a Tailwind class cannot be
        // built from a number at runtime. `repeat(0, …)` is invalid CSS and
        // would drop the whole track list, so a placement-only stage — a legal
        // league with no columns at all — names only the two fixed tracks.
        style={{
          gridTemplateColumns: `minmax(7rem, 1fr) 5rem${
            columns.length > 0 ? ` repeat(${columns.length}, 7rem)` : ""
          }`
        }}
      >
        <span className={EYEBROW_CLASS}>Team</span>
        <span className={EYEBROW_CLASS}>{requiresPlacement ? "Place" : "Place (optional)"}</span>
        {columns.map((column) => (
          <span key={column.key} className={EYEBROW_CLASS}>
            {column.label}
            {!column.public && (
              // The organizer has to know which of these numbers a spectator
              // will never see — this form is the only place the column shows
              // up at all, so nothing else can tell them.
              <span className="block normal-case tracking-normal text-[10px] text-muted-foreground">
                hidden from viewers
              </span>
            )}
          </span>
        ))}
        {rows.map((row) => (
          <FieldRow
            key={row.team_id}
            name={row.team_name}
            columns={columns}
            placement={draft[row.team_id].placement}
            stats={draft[row.team_id].stats}
            flagBlanks={blanksFlagged}
            onPlacement={(value) => setPlacement(row.team_id, value)}
            onStat={(key, value) => setStat(row.team_id, key, value)}
          />
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        {requiresPlacement
          ? `Places run 1 to ${rows.length}, each taken exactly once — this stage's formula pays for them.`
          : "Leave the places empty to derive them from the points; teams on the same points share a place."}
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
  columns,
  placement,
  stats,
  flagBlanks,
  onPlacement,
  onStat
}: Readonly<{
  name: string;
  columns: FfaColumn[];
  placement: number | null;
  stats: Record<string, number | null>;
  flagBlanks: boolean;
  onPlacement: (value: number | null) => void;
  onStat: (key: string, value: number | null) => void;
}>) {
  return (
    <>
      <span className="truncate text-sm text-foreground">{name}</span>
      <NumberInput
        integer
        min={1}
        aria-label={`Place for ${name}`}
        value={placement}
        onValueChange={onPlacement}
      />
      {columns.map((column) => (
        <NumberInput
          key={column.key}
          // NOT `integer`: a column can be a damage share or a half-point
          // penalty, and the server takes any finite 0..1e9 (spec §3.2).
          min={0}
          max={1_000_000_000}
          aria-label={`${column.label} for ${name}`}
          aria-invalid={(flagBlanks && stats[column.key] === null) || undefined}
          className="aria-invalid:border-destructive"
          value={stats[column.key]}
          onValueChange={(value) => onStat(column.key, value)}
        />
      ))}
    </>
  );
}
