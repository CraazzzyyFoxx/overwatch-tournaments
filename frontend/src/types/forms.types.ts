/**
 * The registration form schema, mirroring `backend/shared/domain/forms/schema.py`.
 *
 * One field model for builtins and custom questions alike: a builtin is a field
 * whose `kind` is `"builtin"` and whose `key` names a server-known behaviour
 * (`battle_tag`, `roles`, `identity_discord`, …); everything else is a generic
 * question rendered from `kind`. Answers are a flat `{key: value}` map, so a
 * consumer never needs to know which of the two a key came from.
 */

export type FieldKind =
  | "builtin"
  | "text"
  | "textarea"
  | "number"
  | "select"
  | "multi_select"
  | "checkbox"
  | "url"
  | "date";

/** `organizers` fields are stripped from every public read and never drafted. */
export type Visibility = "public" | "organizers";

/** `visible_when`: show this field only while the condition holds. Evaluated
 *  against the RAW answers, client- and server-side, with identical semantics
 *  (`lib/forms/visible-when.ts` mirrors `validate.py::evaluate_condition`). */
export interface Condition {
  field: string;
  op: "eq" | "neq" | "in" | "truthy";
  value?: unknown;
}

export interface FieldValidation {
  /** Overrides the server's default pattern for the field's key/kind. */
  regex?: string | null;
  error_message?: string | null;
}

export interface FormField {
  key: string;
  kind: FieldKind;
  label?: string | null;
  help?: string | null;
  placeholder?: string | null;
  required: boolean;
  visibility: Visibility;
  /** `select`/`multi_select` only. */
  options?: string[] | null;
  validation?: FieldValidation | null;
  /** Builtin-specific settings; `{}` for every custom field (the schema refuses
   *  params on one). `roles` holds {@link RolesParams}. */
  params: Record<string, unknown>;
  /** Surface this answer in the live draft's player inspector. Public fields only. */
  show_in_draft: boolean;
  visible_when?: Condition | null;
}

export interface FormSection {
  key: string;
  title?: string | null;
  description?: string | null;
  fields: FormField[];
}

export interface FormSchema {
  schema_version: 1;
  sections: FormSection[];
}

/** `params` of the `roles` builtin. Field names mirror
 *  `shared.domain.forms.builtins.RolesParams` verbatim. */
export interface RolesParams {
  primary_required: boolean;
  additional_required: boolean;
  /** False ⇒ an all-primary (full-flex) submission is refused. */
  flex_allowed: boolean;
  flex_mode: "optional" | "all_roles" | "forced";
  /** Role code → allowed sub-role slugs; `{}` means every catalog slug. */
  subroles: Record<string, string[]>;
  top_heroes: { enabled: boolean; required: boolean; max: number };
}

/** A submission's answers, keyed by field key. Values are whatever the field's
 *  kind stores — string, number, boolean, string[], or a role array. */
export type Answers = Record<string, unknown>;

/** One saved schema, reusable across tournaments of a workspace. */
export interface RegistrationFormTemplate {
  id: number;
  workspace_id: number;
  name: string;
  form_schema: FormSchema;
  updated_at: string;
}

export interface RegistrationFormTemplateUpsert {
  name: string;
  form_schema: FormSchema;
}
