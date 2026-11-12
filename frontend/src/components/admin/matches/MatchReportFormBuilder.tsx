"use client";

import { useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { notify } from "@/lib/notify";
import reportFormService from "@/services/report-form.service";
import {
  DEFAULT_MATCH_REPORT_BUILT_INS,
  type MatchReportForm,
  type ReportBuiltInFieldConfig,
  type ReportCustomFieldDefinition
} from "@/types/encounter.types";

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

type BuiltInMode = "off" | "optional" | "required";

/**
 * One standard field as a single choice. "Off" leaves the stored `required` as it was: the field is simply not
 * shown, and the organizer's rule is still there in the saved config.
 */
function BuiltInRow({
  id,
  name,
  hint,
  config,
  modeLabels,
  onChange
}: Readonly<{
  id: string;
  name: string;
  hint: string;
  config: ReportBuiltInFieldConfig;
  modeLabels: Record<BuiltInMode, string>;
  onChange: (updates: Partial<ReportBuiltInFieldConfig>) => void;
}>) {
  const mode: BuiltInMode = !config.enabled ? "off" : config.required ? "required" : "optional";
  return (
    <SettingRow htmlFor={id} label={name} hint={hint}>
      <Select
        value={mode}
        onValueChange={(next) =>
          onChange(next === "off" ? { enabled: false } : { enabled: true, required: next === "required" })
        }
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(["off", "optional", "required"] as const).map((value) => (
            <SelectItem key={value} value={value}>
              {modeLabels[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingRow>
  );
}

/**
 * Per-tournament editor for the captain match-report form, in the settings
 * rail's card language: one card for which of the three optional built-in
 * fields captains see (and must fill in), one for the organizer's own
 * free-text questions, and the shared `SaveBar`. The series score is absent on
 * purpose — it is the input to result derivation, so a report without it would
 * be meaningless.
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
      <PageStateCard
        state="error"
        title={t("loadError")}
        description={formQuery.error instanceof Error ? formQuery.error.message : undefined}
        onAction={() => void formQuery.refetch()}
      />
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
  const modeLabels: Record<BuiltInMode, string> = {
    off: t("modes.off"),
    optional: t("modes.optional"),
    required: t("modes.required")
  };

  return (
    <>
      <SettingsGrid>
        {/* Three fixed rows rather than a table walk: the built-in set is
            frozen by the wire contract, and `t` only accepts literal keys. */}
        <SettingGroup id="standard-fields" title={t("builtInHeading")} description={t("builtInDescription")}>
          <BuiltInRow
            id={`${idBase}-closeness`}
            name={t("fields.closeness")}
            hint={t("fields.closenessHint")}
            config={builtIns.closeness}
            modeLabels={modeLabels}
            onChange={(updates) => updateBuiltIn("closeness", updates)}
          />
          <BuiltInRow
            id={`${idBase}-map-codes`}
            name={t("fields.mapCodes")}
            hint={t("fields.mapCodesHint")}
            config={builtIns.map_codes}
            modeLabels={modeLabels}
            onChange={(updates) => updateBuiltIn("map_codes", updates)}
          />
          <BuiltInRow
            id={`${idBase}-comment`}
            name={t("fields.comment")}
            hint={t("fields.commentHint")}
            config={builtIns.comment}
            modeLabels={modeLabels}
            onChange={(updates) => updateBuiltIn("comment", updates)}
          />
        </SettingGroup>

        <SettingGroup
          id="custom-fields"
          title={t("customHeading")}
          summary={`${customFields.length} / ${MAX_CUSTOM_FIELDS}`}
          description={t("customDescription")}
          actions={
            <>
              {atFieldLimit ? (
                <p id={limitNoticeId} className="text-xs text-muted-foreground">
                  {t("maxFieldsReached")}
                </p>
              ) : null}
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
            </>
          }
        >
          {customFields.length === 0 ? (
            <p className="py-3 text-center text-caption text-muted-foreground">{t("noCustomFields")}</p>
          ) : (
            customFields.map((field, index) => {
              const errors = rowErrors[index];
              const rowId = `${idBase}-${field.uid}`;
              const labelErrorId = `${rowId}-label-error`;
              const keyErrorId = `${rowId}-key-error`;
              const keyHintId = `${rowId}-key-hint`;
              return (
                <div key={field.uid} className="space-y-3 py-4 first:pt-1 last:pb-1">
                  <div className="grid gap-3 @md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor={`${rowId}-label`} className="text-xs">
                        {t("labelLabel")}
                      </Label>
                      <Input
                        id={`${rowId}-label`}
                        value={field.label}
                        aria-invalid={Boolean(errors.label)}
                        aria-describedby={errors.label ? labelErrorId : undefined}
                        onChange={(event) => updateCustomField(field.uid, { label: event.target.value })}
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
                          updateCustomField(field.uid, { key: event.target.value, keyLocked: true })
                        }
                      />
                      <p id={keyHintId} className="text-xs text-muted-foreground">
                        {t("keyHint")}
                      </p>
                      {errors.key ? <FieldError id={keyErrorId} text={errors.key} /> : null}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
                    <div className="min-w-48 flex-1 space-y-1.5">
                      <Label htmlFor={`${rowId}-placeholder`} className="text-xs">
                        {t("placeholderLabel")}
                      </Label>
                      <Input
                        id={`${rowId}-placeholder`}
                        value={field.placeholder ?? ""}
                        onChange={(event) => updateCustomField(field.uid, { placeholder: event.target.value })}
                      />
                    </div>
                    <div className="flex h-9 items-center gap-2">
                      {/* Radix Switch renders a <button>, so a wrapping <label> would not associate. */}
                      <Switch
                        id={`${rowId}-required`}
                        checked={field.required}
                        onCheckedChange={(value) => updateCustomField(field.uid, { required: value })}
                      />
                      <Label htmlFor={`${rowId}-required`} className="text-xs">
                        {t("requiredLabel")}
                      </Label>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-9 text-muted-foreground hover:text-danger"
                      aria-label={t("removeField")}
                      onClick={() => removeCustomField(field.uid)}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </div>
              );
            })
          )}
        </SettingGroup>
      </SettingsGrid>

      <SaveBar
        dirty={hasChanges}
        summary={t("unsavedChanges")}
        error={blockingError}
        saving={saveMutation.isPending}
        onDiscard={() => setDraft(null)}
        // A blocked save is explained in the bar itself; sending it would only buy a 422.
        onSave={() => (blockingError ? undefined : saveMutation.mutate())}
      />
    </>
  );
}
