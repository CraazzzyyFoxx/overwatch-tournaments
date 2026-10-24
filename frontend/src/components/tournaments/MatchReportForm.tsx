"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";

import { EncounterScoreControls } from "@/components/tournaments/EncounterScoreControls";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import captainService, { type CaptainReportSubmitResult } from "@/services/captain.service";
import pickBanService from "@/services/pickBan.service";
import { CaptainReportsView } from "@/components/tournaments/CaptainReportsView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import { buildMapCodeSlots } from "@/components/tournaments/matchReportSlots";
import { reportOf } from "@/lib/encounter/reports";
import { seriesClaimErrors, seriesReportErrorCodes } from "@/lib/encounter/series-claim";
import { isLobby, seatsBySlot } from "@/lib/encounter/seats";
import { modeBeyondMap } from "@/lib/catalog/mode";
import {
  DEFAULT_MATCH_REPORT_BUILT_INS,
  type Encounter,
  type ReportCustomFieldDefinition
} from "@/types/encounter.types";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";

export interface MatchReportFormProps {
  encounter: Encounter;
  /** Ran once the report is accepted. */
  onSubmitted: () => void;
  /** The shell's way out, rendered beside the submit button. */
  cancelAction?: ReactNode;
  /** Extra classes for the field stack; the dialog caps its height, a page does not. */
  fieldsClassName?: string;
}

const MATCH_QUALITY_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

type MatchQuality = (typeof MATCH_QUALITY_OPTIONS)[number];

/** Prefill for a *required* rating with nothing saved to derive one from. */
const DEFAULT_CLOSENESS: MatchQuality = 6;

// Fixed backend caps (see `schemas/encounter_report_form.py`); not organizer-tunable.
const COMMENT_MAX_LENGTH = 1000;
const CUSTOM_TEXT_MAX_LENGTH = 500;

// Module-level so the fallback identity is stable across renders and the memos
// below don't re-run on every keystroke while the config query is in flight.
const EMPTY_CUSTOM_FIELDS: ReportCustomFieldDefinition[] = [];

/** One report field's tile. */
const FIELD_BLOCK_CLASS =
  "rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-4";

function clampCloseness(value: number): MatchQuality {
  return Math.max(1, Math.min(10, Math.round(value))) as MatchQuality;
}

/**
 * Remount key for the form: every value it does not hold in `draft` is derived
 * from the server's numbers, so when THOSE move the untouched fields have to
 * re-derive rather than keep a draft built against the old ones.
 */
export function matchReportDraftKey(encounter: Encounter): string {
  return [encounter.id, encounter.result_version, encounter.closeness ?? "none"].join(":");
}

/**
 * Section heading for one report field. The required/optional state is stated in
 * words so the rule never rides on colour alone. Pass `htmlFor` for a single
 * control (renders a real `<label>`); pass `labelId` for a composite widget that
 * points at it with `aria-labelledby`.
 */
function BlockHeading({
  labelId,
  htmlFor,
  label,
  required,
  hint
}: Readonly<{
  labelId?: string;
  htmlFor?: string;
  label: string;
  required: boolean;
  hint?: string;
}>) {
  const t = useTranslations();

  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <Eyebrow as={htmlFor ? "label" : "p"} id={labelId} htmlFor={htmlFor} tone="dim">
          {label}
        </Eyebrow>
        <span className={cn(eyebrowClass(), "shrink-0", required && "text-[color:var(--aqt-gold)]")}>
          {required ? t("common.required") : t("matchReport.optional")}
        </span>
      </div>
      {hint ? (
        <p className="text-label font-medium text-[color:var(--aqt-fg-dim)]">{hint}</p>
      ) : null}
    </div>
  );
}

/**
 * The series-level captain report: the final score, the closeness rating, one
 * replay code per played map, a comment and whatever custom fields the
 * organizer configured — the whole `matchReport` payload in one form.
 *
 * Shell-agnostic on purpose. `MatchReportDialog` mounts it inside a modal from
 * the bracket; the pre-game room mounts it inline as the loop's last step, once
 * every map has been played and reconciled. Both render the same fields, the
 * same per-field rules and the same submit, so neither can drift.
 *
 * Once the result is confirmed the score is the one on record, shown read-only:
 * a late report still files every other field, and only an organizer moves it.
 */
export function MatchReportForm({
  encounter,
  onSubmitted,
  cancelAction,
  fieldsClassName
}: Readonly<MatchReportFormProps>) {
  const qc = useQueryClient();
  const t = useTranslations();
  const seats = seatsBySlot(encounter.teams);
  const duel = !isLobby(encounter);
  const [first, second] = seats;
  const idPrefix = `match-report-${encounter.id}`;
  const gamesPlayedId = `${idPrefix}-games-played`;

  // The form holds only what the captain has actually edited. Everything else is
  // DERIVED from the server data below, so there is nothing to copy in an effect
  // and nothing that can clobber typed input when a query resolves late.
  // `closeness` is `MatchQuality | null` *and* optional: `undefined` means
  // untouched, an explicit `null` means the captain chose not to rate.
  const [draft, setDraft] = useState<{
    /** Per participation: its wins in a duel, its points in a lobby. */
    scores?: Record<number, number>;
    gamesPlayed?: number;
    closeness?: MatchQuality | null;
    codes?: Record<number, string>;
    comment?: string;
    customFields?: Record<string, string>;
  }>({});

  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.captainReports(encounter.id),
    queryFn: () => captainService.getReports(encounter.id)
  });
  const roleQuery = useQuery({
    queryKey: encounterQueryKeys.myRole(encounter.id),
    queryFn: () => captainService.getMyRole(encounter.id)
  });
  const mapPoolQuery = useQuery({
    queryKey: encounterQueryKeys.mapPickBanState(encounter.id),
    queryFn: () => pickBanService.getPickBanState("map", encounter.id)
  });
  const mapsQuery = useCatalogEntities(encounter.discipline, "map");

  // The per-tournament field config rides the reports envelope. While it is in
  // flight we render the documented defaults rather than an empty form, so the
  // form never grows fields under the captain's cursor.
  const reportForm = reportsQuery.data?.form;
  const builtIns = reportForm?.built_in_fields ?? DEFAULT_MATCH_REPORT_BUILT_INS;
  const customDefs = reportForm?.custom_fields ?? EMPTY_CUSTOM_FIELDS;
  const closenessConfig = builtIns.closeness;
  const mapCodesConfig = builtIns.map_codes;
  const commentConfig = builtIns.comment;

  const slots = useMemo(
    () => buildMapCodeSlots(mapPoolQuery.data, encounter.best_of),
    [mapPoolQuery.data, encounter.best_of]
  );

  const mapNameById = useMemo(() => {
    const lookup = new Map<number, string>();
    for (const map of mapsQuery.data ?? []) {
      lookup.set(map.id, map.name);
    }
    return lookup;
  }, [mapsQuery.data]);

  const ownTeamId = roleQuery.data?.encounter_team_id ?? null;
  const ownReport = useMemo(
    () => reportOf(reportsQuery.data?.reports ?? [], ownTeamId),
    [reportsQuery.data?.reports, ownTeamId]
  );

  // Effective form values: the captain's edit if there is one, else their own
  // saved report, else the encounter's current score. Previously this was an
  // effect that copied `ownReport` into four `useState`s behind a `seededRef`
  // guard — a cascading render plus a race the guard existed to paper over.
  //
  // The encounter's score is what makes this form arrive prefilled at the end
  // of a pre-game loop: `map_report.submit_map_report` counts every reconciled
  // map into it, so the series score is already there to confirm.
  //
  // A confirmed result locks it: the games, an agreement or an organizer
  // decided it, and the server refuses a late report that states another one.
  const locked = encounter.result_status === "confirmed";
  const reported = new Map(ownReport?.results.map((line) => [line.encounter_team_id, line.score]));
  const scores: Record<number, number> = Object.fromEntries(
    seats.map((seat) => [
      seat.id,
      locked ? seat.score : (draft.scores?.[seat.id] ?? reported.get(seat.id) ?? seat.score)
    ])
  );
  const confirmedGames = encounter.games.filter((game) => game.state === "confirmed").length;
  // A duel's score is its wins, so the games it played are at least that many;
  // a lobby's card plays to its end.
  const derivedGamesPlayed = duel
    ? Math.min(
        encounter.best_of,
        Math.max(confirmedGames, Object.values(scores).reduce((sum, value) => sum + value, 0))
      )
    : encounter.best_of;
  // Locked, the captain's own count stands only beside the very score on record
  // (it knows the draws the wins do not); next to any other it would contradict it.
  const gamesPlayed = locked
    ? ((seats.every((seat) => reported.get(seat.id) === seat.score) ? ownReport?.games_played : null) ??
      derivedGamesPlayed)
    : (draft.gamesPlayed ?? ownReport?.games_played ?? derivedGamesPlayed);
  // `encounter.closeness` is a 0..1 float; a report's is 1..10 stars.
  const reportCloseness =
    ownReport?.closeness != null ? clampCloseness(ownReport.closeness) : null;
  const encounterCloseness =
    encounter.closeness != null && encounter.closeness > 0
      ? clampCloseness(encounter.closeness * 10)
      : null;
  // Own report wins outright: a saved report carrying no rating means the
  // captain left it unrated, not "fall back to the encounter's number".
  const savedCloseness = ownReport ? reportCloseness : encounterCloseness;
  // Nothing to derive a rating from: prefill only when the answer is mandatory,
  // otherwise "not rated" has to be the honest starting state.
  const closeness =
    draft.closeness !== undefined
      ? draft.closeness
      : (savedCloseness ?? (closenessConfig.required ? DEFAULT_CLOSENESS : null));
  const codes =
    draft.codes ??
    Object.fromEntries(
      encounter.games.flatMap((game) =>
        game.teams
          .filter((line) => line.encounter_team_id === ownTeamId && line.replay_code)
          .map((line) => [game.position, line.replay_code as string])
      )
    );
  const comment = draft.comment ?? ownReport?.comment ?? "";
  const customValues = draft.customFields ?? ownReport?.custom_fields ?? {};

  // A 2-0 Bo3 played two maps, not three; a forfeit played none. Clamped to the
  // slots that exist so an impossible score cannot demand a code with no input.
  const playedSlots = useMemo(
    () => slots.slice(0, Math.max(0, Math.min(gamesPlayed, slots.length))),
    [slots, gamesPlayed]
  );

  // One pass yields both the per-field messages (for aria-describedby) and the
  // single reason the submit button is disabled, so the two can never disagree.
  const validation = (() => {
    // The same checks, with the same codes, the server runs on a series claim.
    // A locked score is the one on record, not a claim: nothing to check.
    const claimErrors = locked
      ? []
      : seriesClaimErrors({
          preset: encounter.scoring_preset,
          bestOf: encounter.best_of,
          teamIds: seats.map((seat) => seat.id),
          games: encounter.games,
          claim: { gamesPlayed, totals: scores, wins: duel ? scores : null }
        });
    const score = claimErrors.length > 0 ? claimErrors.map((code) => t(`matchReport.errors.${code}`)).join(" ") : null;

    const closenessError =
      closenessConfig.enabled && closenessConfig.required && closeness == null
        ? t("matchReport.fieldRequiredError", { label: t("matchReport.matchQuality") })
        : null;

    const mapCodesError =
      mapCodesConfig.enabled &&
      mapCodesConfig.required &&
      playedSlots.some((slot) => (codes[slot.mapIndex] ?? "").trim().length === 0)
        ? t("matchReport.mapCodesRequiredError")
        : null;

    const commentError =
      commentConfig.enabled && commentConfig.required && comment.trim().length === 0
        ? t("matchReport.commentRequiredError")
        : null;

    const custom: Record<string, string> = {};
    for (const definition of customDefs) {
      if (definition.required && (customValues[definition.key] ?? "").trim().length === 0) {
        custom[definition.key] = t("matchReport.fieldRequiredError", { label: definition.label });
      }
    }

    const firstCustom = customDefs
      .map((definition) => custom[definition.key])
      .find((message) => message != null);

    return {
      score,
      closeness: closenessError,
      mapCodes: mapCodesError,
      comment: commentError,
      custom,
      firstError: score ?? closenessError ?? mapCodesError ?? commentError ?? firstCustom ?? null
    };
  })();

  const validationError = validation.firstError;

  const submitMutation = useMutation({
    mutationFn: () =>
      captainService.submitReport(encounter.id, {
        basis_version: encounter.result_version,
        games_played: gamesPlayed,
        results: seats.map((seat) => ({
          encounter_team_id: seat.id,
          score: scores[seat.id],
          // A duel's rule counts wins, and its score IS its wins; a lobby's card has none.
          wins: duel ? scores[seat.id] : null
        })),
        closeness: closenessConfig.enabled ? closeness : null,
        map_codes: mapCodesConfig.enabled
          ? slots
              .map((slot) => ({
                map_index: slot.mapIndex,
                code: (codes[slot.mapIndex] ?? "").trim()
              }))
              .filter((entry) => entry.code.length > 0)
          : [],
        comment: commentConfig.enabled && comment.trim().length > 0 ? comment.trim() : null,
        custom_fields: Object.fromEntries(
          customDefs
            .map((definition) => [definition.key, (customValues[definition.key] ?? "").trim()])
            .filter(([, value]) => value.length > 0)
        )
      }),
    onSuccess: async (result: CaptainReportSubmitResult) => {
      if (locked) {
        notify.success(t("matchReport.savedAfterConfirmation"));
      } else if (result.result_status === "confirmed") {
        notify.success(t("matchReport.autoConfirmed"));
      } else if (result.result_status === "disputed") {
        notify.error(t("matchReport.autoDisputed"));
      } else {
        notify.success(t("matchReport.submittedForConfirmation"));
      }
      await refreshEncounterViews(qc, encounter.tournament_id);
      onSubmitted();
    },
    onError: (error) => {
      // A code the form knows is worded here, in the captain's language; anything
      // else keeps the server's own message.
      const known = seriesReportErrorCodes(error);
      notify.apiError(error, {
        title: t("matchReport.submitErrorMessage"),
        description:
          known.length > 0
            ? known.map((code) => t(`matchReport.errors.${code}`)).join("\n")
            : getApiErrorMessage(error)
      });
    }
  });

  const qualityLabelId = `${idPrefix}-quality-label`;
  const qualityErrorId = `${idPrefix}-quality-error`;
  const mapCodesLabelId = `${idPrefix}-map-codes-label`;
  const mapCodesErrorId = `${idPrefix}-map-codes-error`;
  const commentId = `${idPrefix}-comment`;
  const commentErrorId = `${commentId}-error`;
  const commentCounterId = `${commentId}-counter`;

  return (
    <>
      <div className={cn("space-y-4", fieldsClassName)}>
        {locked ? (
          <div className={cn("space-y-3", FIELD_BLOCK_CLASS)}>
            <Eyebrow as="p" tone="dim">
              {duel ? t("matchEdit.matchScore") : t("matchReport.pointsLabel")}
            </Eyebrow>
            <dl className="space-y-1.5 text-sm">
              {seats.map((seat) => (
                <div key={seat.id} className="flex items-baseline justify-between gap-3">
                  <dt className="truncate font-semibold text-[color:var(--aqt-fg-muted)]">{seat.name}</dt>
                  <dd className="font-bold tabular-nums text-[color:var(--aqt-fg)]">{scores[seat.id]}</dd>
                </div>
              ))}
              <div className="flex items-baseline justify-between gap-3 border-t border-[color:var(--aqt-border-2)] pt-1.5">
                <dt className="font-semibold text-[color:var(--aqt-fg-muted)]">{t("matchReport.gamesPlayed")}</dt>
                <dd className="font-bold tabular-nums text-[color:var(--aqt-fg)]">{gamesPlayed}</dd>
              </div>
            </dl>
            <p className="text-label font-medium text-[color:var(--aqt-fg-dim)]">
              {t("matchReport.confirmedReportHint")}
            </p>
          </div>
        ) : (
          <>
            {duel ? (
              first &&
              second && (
                <EncounterScoreControls
                  idPrefix={idPrefix}
                  one={scores[first.id]}
                  two={scores[second.id]}
                  firstLabel={first.name}
                  secondLabel={second.name}
                  presetLabel={t("matchReport.quickResult")}
                  bestOf={encounter.best_of}
                  onScoreChange={(score) =>
                    setDraft((prev) => ({
                      ...prev,
                      scores: { ...scores, [first.id]: score.one, [second.id]: score.two }
                    }))
                  }
                />
              )
            ) : (
              <div className={cn("space-y-3", FIELD_BLOCK_CLASS)}>
                <BlockHeading label={t("matchReport.pointsLabel")} required />
                {seats.map((seat) => (
                  <div key={seat.id} className="flex items-center gap-3">
                    <Label
                      htmlFor={`${idPrefix}-points-${seat.id}`}
                      className="w-28 shrink-0 truncate text-xs font-semibold text-[color:var(--aqt-fg-muted)]"
                    >
                      {seat.name}
                    </Label>
                    <NumberInput
                      id={`${idPrefix}-points-${seat.id}`}
                      min={0}
                      value={scores[seat.id]}
                      onValueChange={(next) =>
                        setDraft((prev) => ({ ...prev, scores: { ...scores, [seat.id]: next ?? 0 } }))
                      }
                      variant="surface"
                    />
                  </div>
                ))}
              </div>
            )}

            <div className={cn("space-y-1.5", FIELD_BLOCK_CLASS)}>
              <BlockHeading
                htmlFor={gamesPlayedId}
                label={t("matchReport.gamesPlayed")}
                required
                hint={t("matchReport.gamesPlayedHint")}
              />
              <NumberInput
                id={gamesPlayedId}
                integer
                min={0}
                max={encounter.best_of}
                value={gamesPlayed}
                onValueChange={(next) => setDraft((prev) => ({ ...prev, gamesPlayed: next ?? 0 }))}
                aria-invalid={validation.score != null}
                variant="surface"
              />
            </div>
          </>
        )}

        {closenessConfig.enabled && (
          <div className={cn("space-y-3", FIELD_BLOCK_CLASS)}>
            <div className="flex items-start justify-between gap-3">
              <BlockHeading
                labelId={qualityLabelId}
                label={t("matchReport.matchQuality")}
                required={closenessConfig.required}
                hint={t("matchReport.howClose")}
              />
              <div className="shrink-0 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-3.5 py-1 text-xs font-bold text-[color:var(--aqt-fg)]">
                {closeness == null
                  ? t("matchEdit.notSet")
                  : t(`matchReport.qualityDescriptions.${closeness}`)}
              </div>
            </div>

            <ToggleGroup
              type="single"
              variant="card"
              // A mandatory rating has no "not set" radio, so unset selects nothing.
              value={closeness == null ? (closenessConfig.required ? "" : "none") : String(closeness)}
              onValueChange={(value) =>
                setDraft((prev) => ({
                  ...prev,
                  closeness: MATCH_QUALITY_OPTIONS.find((option) => String(option) === value) ?? null
                }))
              }
              aria-labelledby={qualityLabelId}
              aria-required={closenessConfig.required}
              aria-invalid={validation.closeness != null}
              aria-describedby={validation.closeness ? qualityErrorId : undefined}
              className="grid-cols-5"
            >
              {MATCH_QUALITY_OPTIONS.map((val) => (
                <ToggleGroupItem
                  key={val}
                  value={String(val)}
                  accent="var(--aqt-gold)"
                  aria-label={t("matchReport.qualityAria", {
                    score: String(val),
                    description: t(`matchReport.qualityDescriptions.${val}`)
                  })}
                  className="items-center justify-center text-center"
                >
                  <Star
                    aria-hidden
                    className={cn(
                      "h-4.5 w-4.5 transition-colors duration-150",
                      val === closeness
                        ? "fill-[color:var(--aqt-gold)] text-[color:var(--aqt-gold)]"
                        : "text-[color:var(--aqt-fg-faint)]"
                    )}
                  />
                  <span className="text-label font-bold">{val}/10</span>
                </ToggleGroupItem>
              ))}

              {/* Only an optional rating can be left unset; offering "not rated"
                  for a mandatory one would advertise an invalid answer. */}
              {!closenessConfig.required && (
                <ToggleGroupItem
                  value="none"
                  accent="var(--aqt-fg-muted)"
                  aria-label={t("matchEdit.notSet")}
                  className="col-span-5 items-center"
                >
                  {t("matchEdit.notSet")}
                </ToggleGroupItem>
              )}
            </ToggleGroup>

            {validation.closeness ? (
              <p id={qualityErrorId} className="text-xs font-semibold text-danger">
                {validation.closeness}
              </p>
            ) : null}

            <div className="flex items-center justify-between gap-3 text-label text-[color:var(--aqt-fg-dim)] font-medium pt-1">
              <span>{t("matchReport.qualityLegend.oneSided")}</span>
              <span>{t("matchReport.qualityLegend.toTheEnd")}</span>
            </div>
          </div>
        )}

        {mapCodesConfig.enabled && (
          <div className={cn("space-y-3", FIELD_BLOCK_CLASS)}>
            <BlockHeading
              labelId={mapCodesLabelId}
              label={t("matchReport.mapCodes")}
              required={mapCodesConfig.required}
              hint={mapCodesConfig.required ? t("matchReport.mapCodesRequiredHint") : undefined}
            />
            <div className="space-y-2">
              {slots.map((slot, position) => {
                const name = slot.mapId != null ? mapNameById.get(slot.mapId) : undefined;
                const game = encounter.games?.find((candidate) => candidate.position === slot.mapIndex);
                const mode = modeBeyondMap(game?.map, game?.mode);
                const label =
                  name == null
                    ? t("matchReport.mapLabel", { index: String(position + 1) })
                    : mode == null
                      ? name
                      : `${name} · ${mode.name}`;
                const value = codes[slot.mapIndex] ?? "";
                // `playedSlots` is a prefix of `slots`, so position decides it.
                const isPlayed = position < playedSlots.length;
                const isMissing = mapCodesConfig.required && isPlayed && value.trim().length === 0;
                const inputId = `${idPrefix}-map-code-${slot.mapIndex}`;

                return (
                  <div key={slot.mapIndex} className="flex items-center gap-3">
                    <Label
                      htmlFor={inputId}
                      className="w-28 shrink-0 truncate text-xs font-semibold text-[color:var(--aqt-fg-muted)]"
                    >
                      {label}
                    </Label>
                    <Input
                      id={inputId}
                      value={value}
                      maxLength={32}
                      placeholder={t("matchReport.mapCodePlaceholder")}
                      aria-required={mapCodesConfig.required && isPlayed}
                      aria-invalid={isMissing}
                      aria-describedby={isMissing ? mapCodesErrorId : undefined}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          codes: { ...codes, [slot.mapIndex]: e.target.value }
                        }))
                      }
                      variant="surface"
                    />
                  </div>
                );
              })}
            </div>
            {validation.mapCodes ? (
              <p id={mapCodesErrorId} className="text-xs font-semibold text-danger">
                {validation.mapCodes}
              </p>
            ) : null}
          </div>
        )}

        {commentConfig.enabled && (
          <div className={cn("space-y-2", FIELD_BLOCK_CLASS)}>
            <BlockHeading
              htmlFor={commentId}
              label={t("matchReport.comment")}
              required={commentConfig.required}
            />
            <Textarea
              id={commentId}
              value={comment}
              maxLength={COMMENT_MAX_LENGTH}
              placeholder={t("matchReport.commentPlaceholder")}
              aria-required={commentConfig.required}
              aria-invalid={validation.comment != null}
              aria-describedby={
                validation.comment ? `${commentCounterId} ${commentErrorId}` : commentCounterId
              }
              onChange={(e) => setDraft((prev) => ({ ...prev, comment: e.target.value }))}
              variant="surface"
            />
            <p
              id={commentCounterId}
              className="text-right text-label font-medium tabular-nums text-[color:var(--aqt-fg-dim)]"
            >
              {comment.length}/{COMMENT_MAX_LENGTH}
            </p>
            {validation.comment ? (
              <p id={commentErrorId} className="text-xs font-semibold text-danger">
                {validation.comment}
              </p>
            ) : null}
          </div>
        )}

        {customDefs.length > 0 && (
          <div className={cn("space-y-3", FIELD_BLOCK_CLASS)}>
            <Eyebrow as="p" tone="dim">
              {t("matchReport.customFields")}
            </Eyebrow>
            {customDefs.map((definition) => {
              const inputId = `${idPrefix}-custom-${definition.key}`;
              const errorId = `${inputId}-error`;
              const error = validation.custom[definition.key];

              return (
                <div key={definition.key} className="space-y-1.5">
                  <BlockHeading
                    htmlFor={inputId}
                    label={definition.label}
                    required={definition.required}
                  />
                  <Input
                    id={inputId}
                    value={customValues[definition.key] ?? ""}
                    maxLength={CUSTOM_TEXT_MAX_LENGTH}
                    placeholder={definition.placeholder ?? ""}
                    aria-required={definition.required}
                    aria-invalid={error != null}
                    aria-describedby={error ? errorId : undefined}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        customFields: { ...customValues, [definition.key]: e.target.value }
                      }))
                    }
                    variant="surface"
                  />
                  {error ? (
                    <p id={errorId} className="text-xs font-semibold text-danger">
                      {error}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}

        <CaptainReportsView
          encounter={encounter}
          reports={reportsQuery.data?.reports ?? []}
          form={reportForm}
        />
      </div>

      {/* The per-field errors live inside the field stack above; this footer does
          not. Repeating the first blocking reason here keeps the greyed-out
          submit from ever being unexplained on screen. */}
      <div className="mt-6 flex flex-row flex-wrap items-center justify-end gap-x-4 gap-y-2">
        {validationError ? (
          <output className="mr-auto text-xs font-semibold text-danger">
            {validationError}
          </output>
        ) : null}
        {cancelAction}
        <Button
          onClick={() => submitMutation.mutate()}
          disabled={!!validationError || submitMutation.isPending}
          size="lg"
        >
          {submitMutation.isPending ? t("matchReport.submitting") : t("matchReport.submit")}
        </Button>
      </div>
    </>
  );
}
