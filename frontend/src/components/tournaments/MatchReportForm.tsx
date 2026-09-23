"use client";

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";

import { EncounterScoreControls } from "@/components/tournaments/EncounterScoreControls";
import { getApiErrorMessage, isResultLockedError } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import captainService, { type CaptainReportSubmitResult } from "@/services/captain.service";
import pickBanService from "@/services/pickBan.service";
import mapService from "@/services/map.service";
import { CaptainReportsView } from "@/components/tournaments/CaptainReportsView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import { buildMapCodeSlots } from "@/components/tournaments/matchReportSlots";
import {
  DEFAULT_MATCH_REPORT_BUILT_INS,
  type CaptainReport,
  type Encounter,
  type ReportCustomFieldDefinition
} from "@/types/encounter.types";

export interface MatchReportFormProps {
  encounter: Encounter;
  /**
   * Ran once the report is accepted — and also when the submit reveals the
   * result was confirmed meanwhile, since either way this form is finished.
   */
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

function clampCloseness(value: number): MatchQuality {
  return Math.max(1, Math.min(10, Math.round(value))) as MatchQuality;
}

/**
 * Remount key for the form: every value it does not hold in `draft` is derived
 * from the server's numbers, so when THOSE move the untouched fields have to
 * re-derive rather than keep a draft built against the old ones.
 */
export function matchReportDraftKey(encounter: Encounter): string {
  return [
    encounter.id,
    encounter.score?.home ?? 0,
    encounter.score?.away ?? 0,
    encounter.closeness ?? "none"
  ].join(":");
}

function findOwnReport(
  reports: CaptainReport[],
  side: "home" | "away" | null,
  encounter: Encounter
): CaptainReport | null {
  if (side) {
    const bySide = reports.find((report) => report.side === side);
    if (bySide) return bySide;
    const teamId = side === "home" ? encounter.home_team_id : encounter.away_team_id;
    return reports.find((report) => report.team_id === teamId) ?? null;
  }
  return null;
}

/**
 * Arrow keys that move within a radiogroup, and the direction each one moves.
 * Mirrors `ui/toggle-group.tsx`: declaring `role="radiogroup"` promises the ARIA
 * APG contract — one tab stop, arrows moving *and* selecting — so the grid below
 * has to honour it rather than leave eleven tab stops behind the role.
 */
const RADIO_ARROW_STEP: Record<string, number> = {
  ArrowRight: 1,
  ArrowDown: 1,
  ArrowLeft: -1,
  ArrowUp: -1
};

function moveWithinRadioGroup(event: KeyboardEvent<HTMLDivElement>) {
  const step = RADIO_ARROW_STEP[event.key];
  if (step === undefined) return;

  const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')];
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  if (current === -1) return;

  event.preventDefault();
  const next = items[(current + step + items.length) % items.length];
  next.focus();
  next.click();
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
  const headingClass =
    "text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]";

  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between gap-2">
        {htmlFor ? (
          <label id={labelId} htmlFor={htmlFor} className={headingClass}>
            {label}
          </label>
        ) : (
          <p id={labelId} className={headingClass}>
            {label}
          </p>
        )}
        <span
          className={cn(
            "shrink-0 text-label font-bold uppercase tracking-label",
            required ? "text-[color:var(--aqt-gold)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
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
 * Assumes the result is not confirmed yet — a confirmed encounter accepts no
 * report at all, and each shell says so in its own words before mounting this.
 */
export function MatchReportForm({
  encounter,
  onSubmitted,
  cancelAction,
  fieldsClassName
}: Readonly<MatchReportFormProps>) {
  const qc = useQueryClient();
  const t = useTranslations();
  const homeTeamLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayTeamLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");
  const idPrefix = `match-report-${encounter.id}`;

  // The form holds only what the captain has actually edited. Everything else is
  // DERIVED from the server data below, so there is nothing to copy in an effect
  // and nothing that can clobber typed input when a query resolves late.
  // `closeness` is `MatchQuality | null` *and* optional: `undefined` means
  // untouched, an explicit `null` means the captain chose not to rate.
  const [draft, setDraft] = useState<{
    homeScore?: number;
    awayScore?: number;
    closeness?: MatchQuality | null;
    codes?: Record<number, string>;
    comment?: string;
    customFields?: Record<string, string>;
  }>({});

  const reportsQuery = useQuery({
    queryKey: ["encounter", encounter.id, "reports"],
    queryFn: () => captainService.getReports(encounter.id)
  });
  const roleQuery = useQuery({
    queryKey: ["encounter", encounter.id, "my-role"],
    queryFn: () => captainService.getMyRole(encounter.id)
  });
  const mapPoolQuery = useQuery({
    queryKey: ["encounter", encounter.id, "pick-ban-state", "map"],
    queryFn: () => pickBanService.getPickBanState("map", encounter.id)
  });
  const mapsQuery = useQuery({
    queryKey: ["maps-all"],
    queryFn: () => mapService.getAll({ perPage: -1 }),
    staleTime: 5 * 60 * 1000
  });

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
    for (const map of mapsQuery.data?.results ?? []) {
      lookup.set(map.id, map.name);
    }
    return lookup;
  }, [mapsQuery.data]);

  const ownReport = useMemo(
    () => findOwnReport(reportsQuery.data?.reports ?? [], roleQuery.data?.side ?? null, encounter),
    [reportsQuery.data?.reports, roleQuery.data?.side, encounter]
  );

  // Effective form values: the captain's edit if there is one, else their own
  // saved report, else the encounter's current score. Previously this was an
  // effect that copied `ownReport` into four `useState`s behind a `seededRef`
  // guard — a cascading render plus a race the guard existed to paper over.
  //
  // The encounter's score is what makes this form arrive prefilled at the end
  // of a pre-game loop: `map_report.submit_map_report` counts every reconciled
  // map into it, so the series score is already there to confirm.
  const homeScore = draft.homeScore ?? ownReport?.home_score ?? encounter.score?.home ?? 0;
  const awayScore = draft.awayScore ?? ownReport?.away_score ?? encounter.score?.away ?? 0;
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
    Object.fromEntries((ownReport?.map_codes ?? []).map((code) => [code.map_index, code.code]));
  const comment = draft.comment ?? ownReport?.comment ?? "";
  const customValues = draft.customFields ?? ownReport?.custom_fields ?? {};

  // A 2-0 Bo3 played two maps, not three; a forfeit played none. Clamped to the
  // slots that exist so an impossible score cannot demand a code with no input.
  const playedSlots = useMemo(
    () => slots.slice(0, Math.max(0, Math.min(homeScore + awayScore, slots.length))),
    [slots, homeScore, awayScore]
  );

  // One pass yields both the per-field messages (for aria-describedby) and the
  // single reason the submit button is disabled, so the two can never disagree.
  const validation = useMemo(() => {
    const score = homeScore < 0 || awayScore < 0 ? t("matchEdit.negativeScoreError") : null;

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
  }, [
    homeScore,
    awayScore,
    closeness,
    closenessConfig,
    mapCodesConfig,
    commentConfig,
    playedSlots,
    codes,
    comment,
    customDefs,
    customValues,
    t
  ]);

  const validationError = validation.firstError;

  const submitMutation = useMutation({
    mutationFn: () =>
      captainService.submitReport(encounter.id, {
        home_score: homeScore,
        away_score: awayScore,
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
      if (result.result_status === "confirmed") {
        notify.success(t("matchReport.autoConfirmed"));
      } else if (result.result_status === "disputed") {
        notify.error(t("matchReport.autoDisputed"));
      } else {
        notify.success(t("matchReport.submittedForConfirmation"));
      }
      await refreshEncounterViews(qc, encounter.tournament_id);
      onSubmitted();
    },
    onError: async (error) => {
      if (isResultLockedError(error)) {
        notify.error(t("matchReport.confirmedLockedTitle"), {
          description: t("matchReport.confirmedLockedBody")
        });
        // Data was stale (result got confirmed after this form opened); refresh
        // so the report action disappears, then hand back to the shell.
        await refreshEncounterViews(qc, encounter.tournament_id);
        onSubmitted();
        return;
      }
      notify.apiError(error, {
        title: t("matchReport.submitErrorMessage"),
        description: getApiErrorMessage(error)
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
        <EncounterScoreControls
          idPrefix={idPrefix}
          homeScore={homeScore}
          awayScore={awayScore}
          homeLabel={homeTeamLabel}
          awayLabel={awayTeamLabel}
          presetLabel={t("matchReport.quickResult")}
          bestOf={encounter.best_of}
          onScoreChange={(score) =>
            setDraft((prev) => ({
              ...prev,
              homeScore: score.homeScore,
              awayScore: score.awayScore
            }))
          }
        />

        {closenessConfig.enabled && (
          <div className="space-y-3 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-4">
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

            <div
              role="radiogroup"
              aria-labelledby={qualityLabelId}
              aria-required={closenessConfig.required}
              aria-invalid={validation.closeness != null}
              aria-describedby={validation.closeness ? qualityErrorId : undefined}
              onKeyDown={moveWithinRadioGroup}
              className="grid grid-cols-5 gap-2"
            >
              {MATCH_QUALITY_OPTIONS.map((val, position) => {
                const isSelected = val === closeness;
                // APG: the group is one tab stop. With nothing chosen the first
                // option holds it — a mandatory rating has no "not set" radio to hold it.
                const isTabStop =
                  isSelected || (closeness == null && closenessConfig.required && position === 0);

                return (
                  <button
                    key={val}
                    type="button"
                    role="radio"
                    tabIndex={isTabStop ? 0 : -1}
                    className={cn(
                      "flex min-h-12 flex-col items-center justify-center gap-1 rounded-lg border px-1.5 py-1.5 text-center transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                      isSelected
                        ? "border-[color:color-mix(in_srgb,var(--aqt-gold)_50%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-gold)_12%,transparent)] text-[color:var(--aqt-gold)] hover:bg-[color:color-mix(in_srgb,var(--aqt-gold)_20%,transparent)]"
                        : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                    )}
                    onClick={() => setDraft((prev) => ({ ...prev, closeness: val }))}
                    aria-checked={isSelected}
                    aria-label={t("matchReport.qualityAria", {
                      score: String(val),
                      description: t(`matchReport.qualityDescriptions.${val}`)
                    })}
                  >
                    <Star
                      aria-hidden
                      className={cn(
                        "h-4.5 w-4.5 transition-colors duration-150",
                        isSelected
                          ? "fill-[color:var(--aqt-gold)] text-[color:var(--aqt-gold)]"
                          : "text-[color:var(--aqt-fg-faint)]"
                      )}
                    />
                    <span className="text-label font-bold">{val}/10</span>
                  </button>
                );
              })}

              {/* Only an optional rating can be left unset; offering "not rated"
                  for a mandatory one would advertise an invalid answer. */}
              {!closenessConfig.required && (
                <button
                  type="button"
                  role="radio"
                  tabIndex={closeness == null ? 0 : -1}
                  aria-checked={closeness == null}
                  aria-label={t("matchEdit.notSet")}
                  onClick={() => setDraft((prev) => ({ ...prev, closeness: null }))}
                  className={cn(
                    "col-span-5 min-h-9 rounded-lg border px-2 py-1.5 text-label font-bold uppercase tracking-label transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                    closeness == null
                      ? "border-[color:var(--aqt-border-1)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                      : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg)]"
                  )}
                >
                  {t("matchEdit.notSet")}
                </button>
              )}
            </div>

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
          <div className="space-y-3 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-4">
            <BlockHeading
              labelId={mapCodesLabelId}
              label={t("matchReport.mapCodes")}
              required={mapCodesConfig.required}
              hint={mapCodesConfig.required ? t("matchReport.mapCodesRequiredHint") : undefined}
            />
            <div className="space-y-2">
              {slots.map((slot, position) => {
                const name = slot.mapId != null ? mapNameById.get(slot.mapId) : undefined;
                const label = name ?? t("matchReport.mapLabel", { index: String(position + 1) });
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
                      className="h-9 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-sm text-[color:var(--aqt-fg)]"
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
          <div className="space-y-2 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-4">
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
              className="min-h-20 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-sm text-[color:var(--aqt-fg)]"
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
          <div className="space-y-3 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-4">
            <p className="text-label font-bold uppercase tracking-[0.15em] text-[color:var(--aqt-fg-dim)]">
              {t("matchReport.customFields")}
            </p>
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
                    className="h-9 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-sm text-[color:var(--aqt-fg)]"
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
          className="h-10 px-5 font-bold"
        >
          {submitMutation.isPending ? t("matchReport.submitting") : t("matchReport.submit")}
        </Button>
      </div>
    </>
  );
}
