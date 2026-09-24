"use client";

import { useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, Save, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import reportFormService from "@/services/report-form.service";
import {
  DEFAULT_MATCH_REPORT_BUILT_INS,
  type MatchReportForm,
  type ReportBuiltInFieldConfig,
  type ReportCustomFieldDefinition
} from "@/types/encounter.types";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Spinner } from "@/components/ui/spinner";

type BuiltInKey = keyof MatchReportForm["built_in_fields"];

/** Mirrors the backend `MAX_CUSTOM_FIELDS`; the server rejects a 21st entry. */
const MAX_CUSTOM_FIELDS = 20;

/** Mirrors the backend key grammar, so a bad key never has to become a 422. */
const KEY_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

type CustomFieldDraft = ReportCustomFieldDefinition & {
  /** Stable identity for React keys and input ids; never sent to the server. */
  uid: string;
  /**
   * Once true the label stops driving the key. Rows arriving from the server
   * start locked: re-slugging a saved key from a label edit would orphan every
   * answer already stored under the old key.
   */
  keyLocked: boolean;
};

/** The whole editable config; `null` in state means "untouched, use the server's". */
type BuilderDraft = {
  builtIns: MatchReportForm["built_in_fields"];
  customFields: CustomFieldDraft[];
};

/**
 * Derive a storage key from a human label, inside the backend's key grammar.
 *
 * The grammar demands a leading letter, so a label that starts with a digit
 * ("2v2 notes") gets a prefix instead of a key the server would reject.
 */
function slugifyFieldKey(label: string): string {
  const base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
  if (!base) return "";
  return /^[a-z]/.test(base) ? base : `f_${base}`.slice(0, 32);
}

/** Error text always carries an icon and words — never colour alone. */
function FieldError({ id, text }: Readonly<{ id: string; text: string }>) {
  return (
    <p id={id} className="flex items-start gap-1.5 text-xs text-danger">
      <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
      {text}
    </p>
  );
}

function ToggleCell({
  id,
  label,
  checked,
  disabled,
  describedBy,
  onCheckedChange
}: Readonly<{
  id: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  describedBy?: string;
  onCheckedChange: (value: boolean) => void;
}>) {
  return (
    <div className="flex min-w-20 flex-col items-start gap-1.5">
      {/* Radix Switch renders a <button>, so a wrapping <label> would not
          associate. The id/htmlFor pair does. */}
      <Label htmlFor={id} className={cn("text-xs", disabled && "text-muted-foreground")}>
        {label}
      </Label>
      <Switch
        id={id}
        checked={checked}
        disabled={disabled}
        aria-describedby={describedBy}
        onCheckedChange={onCheckedChange}
      />
    </div>
  );
}

function BuiltInRow({
  idBase,
  name,
  hint,
  config,
  enabledLabel,
  requiredLabel,
  onChange
}: Readonly<{
  idBase: string;
  name: string;
  hint: string;
  config: ReportBuiltInFieldConfig;
  enabledLabel: string;
  requiredLabel: string;
  onChange: (updates: Partial<ReportBuiltInFieldConfig>) => void;
}>) {
  const hintId = `${idBase}-hint`;
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4 rounded-lg border border-[color:var(--aqt-border)] p-4">
      <div className="min-w-56 max-w-prose flex-1 space-y-1">
        <p className="text-sm font-medium">{name}</p>
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      </div>
      <div className="flex shrink-0 gap-4">
        <ToggleCell
          id={`${idBase}-enabled`}
          label={enabledLabel}
          checked={config.enabled}
          describedBy={hintId}
          onCheckedChange={(value) => onChange({ enabled: value })}
        />
        <ToggleCell
          id={`${idBase}-required`}
          label={requiredLabel}
          checked={config.required}
          // A field nobody is shown cannot be mandatory. The stored value stays
          // put, so re-enabling the field restores the organizer's choice.
          disabled={!config.enabled}
          describedBy={hintId}
          onCheckedChange={(value) => onChange({ required: value })}
        />
      </div>
    </div>
  );
}

/**
 * Per-tournament editor for the captain match-report form.
 *
 * Two concerns in one panel: which of the three optional built-in fields
 * captains see (and must fill in), and the organizer's own free-text questions.
 * The series score is absent on purpose — it is the input to result derivation,
 * so a report without it would be meaningless.
 *
 * The backend is the validation authority; the inline checks here exist so the
 * organizer sees a bad key before a 422 does.
 */
export function MatchReportFormBuilder({ tournamentId }: Readonly<{ tournamentId: number }>) {
  const t = useTranslations("matchReportFormAdmin");
  const queryClient = useQueryClient();
  const idBase = useId();

  const queryKey = useMemo(() => ["admin", "report-form", tournamentId], [tournamentId]);

  const formQuery = useQuery({
    queryKey,
    queryFn: () => reportFormService.getReportForm(tournamentId),
    // A long-lived editor: a background refetch must not clobber unsaved edits.
    refetchOnWindowFocus: false
  });

  /**
   * The editor renders from the server config until the organizer touches
   * something; only then does a `draft` exist. That keeps a background refetch
   * from clobbering unsaved edits WITHOUT an effect copying query data into
   * state — the same derived-value contract `MatchReportDialog` follows.
   */
  const [draft, setDraft] = useState<BuilderDraft | null>(null);
  const uidCounter = useRef(0);

  const serverConfig = useMemo<BuilderDraft>(
    () => ({
      builtIns: { ...DEFAULT_MATCH_REPORT_BUILT_INS, ...(formQuery.data?.built_in_fields ?? {}) },
      customFields: (formQuery.data?.custom_fields ?? []).map((field, index) => ({
        ...field,
        uid: `s${index}`,
        // A saved key must never re-slug from a label edit: every answer already
        // stored under the old key would be orphaned.
        keyLocked: true
      }))
    }),
    [formQuery.data]
  );

  const { builtIns, customFields } = draft ?? serverConfig;
  const hasChanges = draft !== null;

  const editDraft = (apply: (current: BuilderDraft) => BuilderDraft) =>
    setDraft((previous) => apply(previous ?? { builtIns, customFields }));

  const rowErrors = useMemo(() => {
    const keyCounts = new Map<string, number>();
    for (const field of customFields) {
      keyCounts.set(field.key, (keyCounts.get(field.key) ?? 0) + 1);
    }
    return customFields.map((field) => {
      let keyError: string | null = null;
      if (!KEY_PATTERN.test(field.key)) {
        keyError = t("errors.keyInvalid");
      } else if ((keyCounts.get(field.key) ?? 0) > 1) {
        // Both halves of a collision are flagged: seeing only the second one
        // leaves the organizer guessing which row to rename.
        keyError = t("errors.keyDuplicate");
      }
      return {
        label: field.label.trim() ? null : t("errors.labelRequired"),
        key: keyError
      };
    });
  }, [customFields, t]);

  const blockingError = rowErrors.flatMap((row) => [row.label, row.key]).find(Boolean) ?? null;
  const atFieldLimit = customFields.length >= MAX_CUSTOM_FIELDS;

  const saveMutation = useMutation({
    mutationFn: () =>
      reportFormService.saveReportForm(tournamentId, {
        built_in_fields: builtIns,
        custom_fields: customFields.map((field) => ({
          key: field.key,
          label: field.label.trim(),
          type: "text" as const,
          required: field.required,
          // A blank placeholder is absence, not an empty hint under the input.
          placeholder: field.placeholder?.trim() ? field.placeholder.trim() : null
        }))
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      setDraft(null);
      notify.success(t("saved"));
    },
    onError: (error) => notify.apiError(error, { title: t("saveError") })
  });

  const updateBuiltIn = (key: BuiltInKey, updates: Partial<ReportBuiltInFieldConfig>) =>
    editDraft((current) => ({
      ...current,
      builtIns: { ...current.builtIns, [key]: { ...current.builtIns[key], ...updates } }
    }));

  const addCustomField = () => {
    uidCounter.current += 1;
    const uid = `n${uidCounter.current}`;
    editDraft((current) => ({
      ...current,
      customFields: [
        ...current.customFields,
        {
          uid,
          key: "",
          label: "",
          type: "text",
          required: false,
          placeholder: null,
          keyLocked: false
        }
      ]
    }));
  };

  const updateCustomField = (uid: string, updates: Partial<CustomFieldDraft>) =>
    editDraft((current) => ({
      ...current,
      customFields: current.customFields.map((field) => {
        if (field.uid !== uid) return field;
        const next = { ...field, ...updates };
        if (updates.label !== undefined && !field.keyLocked) {
          next.key = slugifyFieldKey(updates.label);
        }
        return next;
      })
    }));

  const removeCustomField = (uid: string) =>
    editDraft((current) => ({
      ...current,
      customFields: current.customFields.filter((field) => field.uid !== uid)
    }));

  if (formQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{t("loadError")}</AlertTitle>
        {formQuery.error instanceof Error ? (
          <AlertDescription>{formQuery.error.message}</AlertDescription>
        ) : null}
      </Alert>
    );
  }

  // Skeletons rather than the defaults: showing "enabled, required" toggles the
  // organizer never chose reads as saved configuration.
  if (formQuery.isLoading) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  const limitNoticeId = `${idBase}-limit`;
  const saveBlockedId = `${idBase}-blocked`;

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle asChild className="text-base font-semibold">
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        <section aria-labelledby={`${idBase}-built-in`} className="space-y-3">
          <div className="space-y-1">
            <h3 id={`${idBase}-built-in`} className={EYEBROW_CLASS}>
              {t("builtInHeading")}
            </h3>
            <p className="text-xs text-muted-foreground">{t("builtInDescription")}</p>
          </div>
          {/* Three fixed rows rather than a table walk: the built-in set is
              frozen by the wire contract, and `t` only accepts literal keys. */}
          <div className="space-y-2">
            <BuiltInRow
              idBase={`${idBase}-closeness`}
              name={t("fields.closeness")}
              hint={t("fields.closenessHint")}
              config={builtIns.closeness}
              enabledLabel={t("enabledLabel")}
              requiredLabel={t("requiredLabel")}
              onChange={(updates) => updateBuiltIn("closeness", updates)}
            />
            <BuiltInRow
              idBase={`${idBase}-map-codes`}
              name={t("fields.mapCodes")}
              hint={t("fields.mapCodesHint")}
              config={builtIns.map_codes}
              enabledLabel={t("enabledLabel")}
              requiredLabel={t("requiredLabel")}
              onChange={(updates) => updateBuiltIn("map_codes", updates)}
            />
            <BuiltInRow
              idBase={`${idBase}-comment`}
              name={t("fields.comment")}
              hint={t("fields.commentHint")}
              config={builtIns.comment}
              enabledLabel={t("enabledLabel")}
              requiredLabel={t("requiredLabel")}
              onChange={(updates) => updateBuiltIn("comment", updates)}
            />
          </div>
        </section>

        <section
          aria-labelledby={`${idBase}-custom`}
          className="space-y-3 border-t border-border/30 pt-6"
        >
          <div className="space-y-1">
            <h3 id={`${idBase}-custom`} className={EYEBROW_CLASS}>
              {t("customHeading")}
            </h3>
            <p className="text-xs text-muted-foreground">{t("customDescription")}</p>
          </div>

          {customFields.length === 0 ? (
            <EmptyNote className="text-center">{t("noCustomFields")}</EmptyNote>
          ) : (
            <ul className="space-y-3">
              {customFields.map((field, index) => {
                const errors = rowErrors[index];
                const rowId = `${idBase}-${field.uid}`;
                const labelErrorId = `${rowId}-label-error`;
                const keyErrorId = `${rowId}-key-error`;
                const keyHintId = `${rowId}-key-hint`;
                return (
                  <li
                    key={field.uid}
                    className="space-y-3 rounded-lg border border-[color:var(--aqt-border)] p-4"
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor={`${rowId}-label`} className="text-xs">
                          {t("labelLabel")}
                        </Label>
                        <Input
                          id={`${rowId}-label`}
                          value={field.label}
                          aria-invalid={Boolean(errors.label)}
                          aria-describedby={errors.label ? labelErrorId : undefined}
                          onChange={(event) =>
                            updateCustomField(field.uid, { label: event.target.value })
                          }
                        />
                        {errors.label ? <FieldError id={labelErrorId} text={errors.label} /> : null}
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor={`${rowId}-key`} className="text-xs">
                          {t("keyLabel")}
                        </Label>
                        <Input
                          id={`${rowId}-key`}
                          value={field.key}
                          className="font-mono"
                          aria-invalid={Boolean(errors.key)}
                          aria-describedby={errors.key ? `${keyHintId} ${keyErrorId}` : keyHintId}
                          onChange={(event) =>
                            updateCustomField(field.uid, {
                              key: event.target.value,
                              keyLocked: true
                            })
                          }
                        />
                        <p id={keyHintId} className="text-xs text-muted-foreground">
                          {t("keyHint")}
                        </p>
                        {errors.key ? <FieldError id={keyErrorId} text={errors.key} /> : null}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
                      <div className="min-w-56 flex-1 space-y-1.5">
                        <Label htmlFor={`${rowId}-placeholder`} className="text-xs">
                          {t("placeholderLabel")}
                        </Label>
                        <Input
                          id={`${rowId}-placeholder`}
                          value={field.placeholder ?? ""}
                          onChange={(event) =>
                            updateCustomField(field.uid, { placeholder: event.target.value })
                          }
                        />
                      </div>
                      <div className="flex items-end gap-4">
                        <ToggleCell
                          id={`${rowId}-required`}
                          label={t("requiredLabel")}
                          checked={field.required}
                          onCheckedChange={(value) =>
                            updateCustomField(field.uid, { required: value })
                          }
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-danger hover:text-danger"
                          onClick={() => removeCustomField(field.uid)}
                        >
                          <Trash2 aria-hidden />
                          {t("removeField")}
                        </Button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={atFieldLimit}
              aria-describedby={atFieldLimit ? limitNoticeId : undefined}
              onClick={addCustomField}
            >
              <Plus aria-hidden />
              {t("addField")}
            </Button>
            {atFieldLimit ? (
              <p id={limitNoticeId} className="text-xs text-muted-foreground">
                {t("maxFieldsReached")}
              </p>
            ) : null}
          </div>
        </section>
      </CardContent>

      <CardFooter className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 border-t border-border/30 pt-6">
        {blockingError ? <FieldError id={saveBlockedId} text={blockingError} /> : null}
        <Button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || Boolean(blockingError) || !hasChanges}
          aria-describedby={blockingError ? saveBlockedId : undefined}
        >
          {saveMutation.isPending ? (
            <Spinner />
          ) : (
            <Save aria-hidden />
          )}
          {saveMutation.isPending ? t("saving") : t("save")}
        </Button>
      </CardFooter>
    </Card>
  );
}
