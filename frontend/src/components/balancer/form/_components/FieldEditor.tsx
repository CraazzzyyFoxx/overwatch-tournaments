"use client";

import { useId, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { builtinFixedVisibility, builtinParamsKind } from "@/lib/forms/builtin-keys";
import { cn } from "@/lib/utils";
import type { Condition, FormField, Visibility } from "@/types/forms.types";

import {
  RolesParamsEditor,
  SwitchRow,
  rolesParamsOf,
  type SubroleCatalogByRole
} from "./RolesParamsEditor";
import {
  MAX_REGEX_LENGTH,
  fieldDisplayLabel,
  fieldIssues,
  supportsValidation
} from "./schemaEdits";

const OPTION_KINDS: Record<string, true> = { select: true, multi_select: true };

const CONDITION_OPS = ["truthy", "eq", "neq", "in"] as const;

/**
 * Builtins the SERVER re-locks on its own, whatever this switch says, and the
 * hint that has to name that floor.
 *
 * The control stays enabled for them: the floor is a lower bound, so an
 * organizer may legitimately freeze `battle_tag` or `roles` EARLIER than the
 * server would. Stating the floor beats silently overriding the switch.
 *
 * Valued with message-key LITERALS, not `string`: the translator is typed
 * against the message tree, so a widened key would not resolve.
 */
const EDITABLE_HINT_KEY: Record<string, "editableHintBattleTag" | "editableHintRoles"> = {
  battle_tag: "editableHintBattleTag",
  roles: "editableHintRoles"
};

/** One labelled block of the panel. Space and an eyebrow, no extra boxes: the
 *  panel already sits on its own surface inside the question list. */
function Group({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="grid gap-3">
      <h4 className={EYEBROW_CLASS}>{title}</h4>
      {children}
    </section>
  );
}

/** The control a `visible_when` value needs, derived from the field it targets. */
function conditionValueKind(target: FormField | undefined): "boolean" | "number" | "options" | "text" {
  if (!target) return "text";
  if (target.key === "stream_pov" || target.kind === "checkbox") return "boolean";
  if (target.kind === "number") return "number";
  if (OPTION_KINDS[target.kind]) return "options";
  return "text";
}

function ConditionValueInput({
  id,
  condition,
  target,
  onChange
}: Readonly<{
  id: string;
  condition: Condition;
  target: FormField | undefined;
  onChange: (value: unknown) => void;
}>) {
  const t = useTranslations("registrationFormAdmin.field");
  const kind = conditionValueKind(target);
  const options = (target?.options ?? []).map((option) => option.trim()).filter(Boolean);

  if (condition.op === "in") {
    const selected = Array.isArray(condition.value) ? (condition.value as unknown[]) : [];
    if (kind === "options") {
      return (
        <div className="flex flex-wrap gap-1.5">
          {options.map((option) => {
            const on = selected.includes(option);
            return (
              <label
                key={option}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() =>
                    onChange(
                      on ? selected.filter((item) => item !== option) : [...selected, option]
                    )
                  }
                />
                {option}
              </label>
            );
          })}
        </div>
      );
    }
    return (
      <Input
        id={id}
        value={selected.join(", ")}
        placeholder={t("visibleWhenListPlaceholder")}
        onChange={(event) =>
          onChange(
            event.target.value
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean)
          )
        }
      />
    );
  }

  if (kind === "boolean") {
    return (
      <Select value={condition.value === true ? "true" : "false"} onValueChange={(v) => onChange(v === "true")}>
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">{t("valueTrue")}</SelectItem>
          <SelectItem value="false">{t("valueFalse")}</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  if (kind === "options") {
    return (
      <Select
        value={typeof condition.value === "string" ? condition.value : ""}
        onValueChange={onChange}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (kind === "number") {
    return (
      <Input
        id={id}
        type="number"
        value={typeof condition.value === "number" ? condition.value : ""}
        onChange={(event) => {
          const parsed = Number(event.target.value);
          onChange(event.target.value === "" || !Number.isFinite(parsed) ? null : parsed);
        }}
      />
    );
  }

  return (
    <Input
      id={id}
      value={typeof condition.value === "string" ? condition.value : ""}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/**
 * Everything one question decides, on one panel.
 *
 * The panel is built so the server's schema invariants are UNREACHABLE rather
 * than merely reported: a builtin whose visibility the catalog fixes gets a
 * disabled selector with the reason, the `visible_when` picker lists only fields
 * that come EARLIER in flattened order, and a custom field's key is derived from
 * its label exactly once. What is left — an empty label, an empty option list, a
 * pattern that will not compile — is shown inline and blocks the save.
 */
export function FieldEditor({
  field,
  earlierFields,
  keyLocked,
  serverError,
  catalog,
  catalogLoading = false,
  onChange,
  onCommitKey
}: Readonly<{
  field: FormField;
  /** Fields BEFORE this one in flattened order — the only legal condition targets. */
  earlierFields: FormField[];
  keyLocked: boolean;
  /** A `schema_invalid` rejection the server filed against this field. */
  serverError: string | null;
  catalog: SubroleCatalogByRole;
  catalogLoading?: boolean;
  onChange: (next: FormField) => void;
  onCommitKey: () => void;
}>) {
  const t = useTranslations("registrationFormAdmin.field");
  const tBuiltins = useTranslations("registrationFormAdmin.builtins");
  const ids = useId();

  const isBuiltin = field.kind === "builtin";
  const fixedVisibility = isBuiltin ? builtinFixedVisibility(field.key) : null;
  const paramsKind = isBuiltin ? builtinParamsKind(field.key) : null;
  const issues = fieldIssues(field);
  const condition = field.visible_when ?? null;
  const target = condition
    ? earlierFields.find((candidate) => candidate.key === condition.field)
    : undefined;

  const setVisibility = (visibility: Visibility) => onChange({ ...field, visibility });

  const setCondition = (next: Condition | null) => onChange({ ...field, visible_when: next });

  return (
    <div className="grid gap-5 border-t pt-4">
      {serverError ? (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
        >
          {serverError}
        </p>
      ) : null}

      <Group title={t("groupQuestion")}>
        {isBuiltin ? (
          <p className="text-xs text-muted-foreground">{t("builtinCopyHint")}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${ids}-label`} className="text-xs">
                {t("label")}
              </Label>
              <Input
                id={`${ids}-label`}
                value={field.label ?? ""}
                placeholder={t("labelPlaceholder")}
                aria-invalid={issues.label !== null}
                aria-describedby={`${ids}-label-note`}
                onChange={(event) => onChange({ ...field, label: event.target.value })}
                onBlur={onCommitKey}
              />
              {/* One note slot: the objection if there is one, otherwise what
                  the answer key is — the thing every stored answer is filed
                  under, so it is never silently off screen. */}
              <p
                id={`${ids}-label-note`}
                className={cn(
                  "text-xs",
                  issues.label || issues.key ? "text-destructive" : "text-muted-foreground"
                )}
              >
                {issues.label
                  ? t(`issues.${issues.label}`)
                  : issues.key
                    ? t(`issues.${issues.key}`, { key: field.key })
                    : keyLocked
                      ? t("keyLocked", { key: field.key })
                      : t("keyPending", { key: field.key })}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${ids}-placeholder`} className="text-xs">
                {t("placeholder")}
              </Label>
              <Input
                id={`${ids}-placeholder`}
                value={field.placeholder ?? ""}
                onChange={(event) =>
                  onChange({ ...field, placeholder: event.target.value || null })
                }
              />
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor={`${ids}-help`} className="text-xs">
                {t("help")}
              </Label>
              <Input
                id={`${ids}-help`}
                value={field.help ?? ""}
                onChange={(event) => onChange({ ...field, help: event.target.value || null })}
              />
            </div>
          </div>
        )}

        {OPTION_KINDS[field.kind] ? (
          <div className="grid gap-1.5">
            <Label htmlFor={`${ids}-options`} className="text-xs">
              {t("options")}
            </Label>
            <Textarea
              id={`${ids}-options`}
              rows={4}
              value={(field.options ?? []).join("\n")}
              placeholder={t("optionsPlaceholder")}
              aria-invalid={issues.options !== null}
              aria-describedby={issues.options ? `${ids}-options-error` : undefined}
              onChange={(event) => onChange({ ...field, options: event.target.value.split("\n") })}
            />
            {issues.options ? (
              <p id={`${ids}-options-error`} className="text-xs text-destructive">
                {t(`issues.${issues.options}`)}
              </p>
            ) : null}
          </div>
        ) : null}
      </Group>

      <Group title={t("groupAnswer")}>
        <SwitchRow
          id={`${ids}-required`}
          label={t("required")}
          checked={field.required}
          onCheckedChange={(required) => onChange({ ...field, required })}
        />

        {paramsKind === "battle_tag" || paramsKind === "identity" ? (
          <SwitchRow
            id={`${ids}-verified`}
            label={t("requireVerified")}
            hint={t("requireVerifiedHint")}
            checked={field.params.require_verified === true}
            onCheckedChange={(require_verified) =>
              onChange({ ...field, params: { ...field.params, require_verified } })
            }
          />
        ) : null}

        {supportsValidation(field) ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${ids}-regex`} className="text-xs">
                {t("regex")}
              </Label>
              <Input
                id={`${ids}-regex`}
                className="font-mono"
                value={field.validation?.regex ?? ""}
                aria-invalid={issues.regex !== null}
                aria-describedby={`${ids}-regex-note`}
                onChange={(event) =>
                  onChange({
                    ...field,
                    validation: {
                      ...(field.validation ?? {}),
                      regex: event.target.value || null
                    }
                  })
                }
              />
              <p
                id={`${ids}-regex-note`}
                className={cn("text-xs", issues.regex ? "text-destructive" : "text-muted-foreground")}
              >
                {issues.regex
                  ? t(`issues.${issues.regex}`, { max: MAX_REGEX_LENGTH })
                  : t("regexHint")}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${ids}-regex-message`} className="text-xs">
                {t("errorMessage")}
              </Label>
              <Input
                id={`${ids}-regex-message`}
                value={field.validation?.error_message ?? ""}
                onChange={(event) =>
                  onChange({
                    ...field,
                    validation: {
                      ...(field.validation ?? {}),
                      error_message: event.target.value || null
                    }
                  })
                }
              />
            </div>
          </div>
        ) : null}
      </Group>

      <Group title={t("groupVisibility")}>
        <div className="grid gap-1.5">
          <Label htmlFor={`${ids}-visibility`} className="text-xs">
            {t("visibility")}
          </Label>
          <Select
            value={field.visibility}
            disabled={fixedVisibility !== null}
            onValueChange={(value) => setVisibility(value as Visibility)}
          >
            <SelectTrigger id={`${ids}-visibility`} aria-describedby={`${ids}-visibility-note`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="public">{t("visibilityPublic")}</SelectItem>
              <SelectItem value="organizers">{t("visibilityOrganizers")}</SelectItem>
            </SelectContent>
          </Select>
          <p id={`${ids}-visibility-note`} className="text-xs text-muted-foreground">
            {fixedVisibility
              ? t("visibilityFixed", { field: fieldDisplayLabel(field, tBuiltins) })
              : t("visibilityHint")}
          </p>
        </div>

        <SwitchRow
          id={`${ids}-editable`}
          label={t("editable")}
          hint={t(EDITABLE_HINT_KEY[field.key] ?? "editableHint")}
          checked={field.editable === true}
          onCheckedChange={(editable) => onChange({ ...field, editable })}
        />
      </Group>

      <Group title={t("groupCondition")}>
        <div className="grid gap-1.5">
          <Label htmlFor={`${ids}-when`} className="text-xs">
            {t("visibleWhen")}
          </Label>
          <Select
            value={condition?.field ?? ""}
            // Nothing earlier to point at is a dead dropdown, not a choice.
            disabled={earlierFields.length === 0}
            onValueChange={(value) =>
              // `truthy` is the default because it is the only operator that
              // reads correctly against every kind, and it needs no value.
              setCondition(value === "" ? null : { field: value, op: "truthy" })
            }
          >
            <SelectTrigger id={`${ids}-when`} aria-describedby={`${ids}-when-note`}>
              <SelectValue placeholder={t("visibleWhenAlways")} />
            </SelectTrigger>
            <SelectContent>
              {earlierFields.map((candidate) => (
                <SelectItem key={candidate.key} value={candidate.key}>
                  {fieldDisplayLabel(candidate, tBuiltins)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p id={`${ids}-when-note`} className="text-xs text-muted-foreground">
            {earlierFields.length === 0 ? t("visibleWhenNoEarlier") : t("visibleWhenHint")}
          </p>
        </div>

        {condition ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${ids}-op`} className="text-xs">
                {t("visibleWhenOp")}
              </Label>
              <Select
                value={condition.op}
                onValueChange={(value) =>
                  setCondition({
                    field: condition.field,
                    op: value as Condition["op"],
                    ...(value === "truthy" ? {} : { value: value === "in" ? [] : condition.value })
                  })
                }
              >
                <SelectTrigger id={`${ids}-op`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONDITION_OPS.map((op) => (
                    <SelectItem key={op} value={op}>
                      {t(`op_${op}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {condition.op === "truthy" ? null : (
              <div className="grid gap-1.5">
                <Label htmlFor={`${ids}-value`} className="text-xs">
                  {t("visibleWhenValue")}
                </Label>
                <ConditionValueInput
                  id={`${ids}-value`}
                  condition={condition}
                  target={target}
                  onChange={(value) => setCondition({ ...condition, value })}
                />
              </div>
            )}
            <Button
              variant="link"
              size="sm"
              className="h-auto justify-self-start p-0"
              onClick={() => setCondition(null)}
            >
              {t("visibleWhenClear")}
            </Button>
          </div>
        ) : null}
      </Group>

      {paramsKind === "roles" ? (
        <Group title={t("groupParams")}>
          <RolesParamsEditor
            params={rolesParamsOf(field.params)}
            onChange={(params) => onChange({ ...field, params: { ...params } })}
            catalog={catalog}
            catalogLoading={catalogLoading}
          />
        </Group>
      ) : null}
    </div>
  );
}
