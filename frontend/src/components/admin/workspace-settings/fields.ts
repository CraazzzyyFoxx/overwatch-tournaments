import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";
import type { Workspace } from "@/types/workspace.types";
import type { WorkspaceRecordSectionKey } from "./sections";

/**
 * Blank text -> `null`.
 *
 * Both the brand colours and the SEO/subdomain strings need it: the backend
 * rejects `""` for a colour (the `#RRGGBB` pattern) and a missing token falls
 * back to the derived default, while an empty subdomain means "platform URL
 * only" rather than a subdomain named "".
 */
const trimOrNull = (value: string | null) => value?.trim() || null;

/**
 * One field definition: which section owns it, how it is read off the
 * workspace, and how it is normalised on the wire.
 *
 * Built through a helper rather than written as a plain object so the read
 * type survives — `FIELD_DEFS` is the single source of the form type, the
 * payload shape and the section split, where the pre-redesign screen spelled
 * the same twenty fields out three times (an interface, a `formFromWorkspace`
 * and a `buildPayload`) and let them drift.
 */
const field = <T,>(
  section: WorkspaceRecordSectionKey,
  from: (ws: Workspace) => T,
  wire?: (value: T) => T
) => ({ section, from, wire }) as const;

export const FIELD_DEFS = {
  name: field("general", (ws) => ws.name),
  description: field("general", (ws) => ws.description ?? ""),
  timezone: field("general", (ws) => ws.timezone ?? DEFAULT_WORKSPACE_TIMEZONE),

  branding_enabled: field("branding", (ws) => ws.branding_enabled),
  brand_primary: field("branding", (ws) => ws.brand_primary, trimOrNull),
  brand_secondary: field("branding", (ws) => ws.brand_secondary, trimOrNull),
  brand_background: field("branding", (ws) => ws.brand_background, trimOrNull),
  brand_surface: field("branding", (ws) => ws.brand_surface, trimOrNull),
  brand_accent: field("branding", (ws) => ws.brand_accent ?? null, trimOrNull),
  brand_foreground: field("branding", (ws) => ws.brand_foreground ?? null, trimOrNull),
  brand_muted: field("branding", (ws) => ws.brand_muted ?? null, trimOrNull),
  brand_border: field("branding", (ws) => ws.brand_border ?? null, trimOrNull),
  brand_ring: field("branding", (ws) => ws.brand_ring ?? null, trimOrNull),
  brand_destructive: field("branding", (ws) => ws.brand_destructive ?? null, trimOrNull),

  is_hidden: field("visibility", (ws) => ws.is_hidden),
  newcomer_scope: field("visibility", (ws) => ws.newcomer_scope ?? "global"),

  subdomain: field("domain", (ws) => ws.subdomain, trimOrNull),
  seo_title: field("domain", (ws) => ws.seo_title, trimOrNull),
  seo_description: field("domain", (ws) => ws.seo_description, trimOrNull)
};

export type WorkspaceFieldKey = keyof typeof FIELD_DEFS;

/** The editable form, typed straight off `FIELD_DEFS`. */
export type WorkspaceSettingsFormState = {
  [K in WorkspaceFieldKey]: ReturnType<(typeof FIELD_DEFS)[K]["from"]>;
};

const FIELD_KEYS = Object.keys(FIELD_DEFS) as WorkspaceFieldKey[];

export function formFromWorkspace(ws: Workspace): WorkspaceSettingsFormState {
  const form = {} as Record<WorkspaceFieldKey, unknown>;
  for (const key of FIELD_KEYS) form[key] = FIELD_DEFS[key].from(ws);
  return form as WorkspaceSettingsFormState;
}

/**
 * The exact wire values a save would send, so the diff below and the request
 * body use identical normalisation — otherwise an untouched field could still
 * "change" from raw to trimmed and pollute the audit trail with a no-op SET
 * (`WorkspaceUpdate.model_dump(exclude_unset=True)` records exactly the keys a
 * PATCH sends).
 */
export function buildPayload(form: WorkspaceSettingsFormState): WorkspaceSettingsFormState {
  const payload = { ...form } as Record<WorkspaceFieldKey, unknown>;
  for (const key of FIELD_KEYS) {
    const { wire } = FIELD_DEFS[key];
    // `wire` is a union of per-field normalisers; the key it is read under is
    // the key its value comes from, which the indexed access cannot express.
    if (wire) payload[key] = (wire as (value: unknown) => unknown)(form[key]);
  }
  return payload as WorkspaceSettingsFormState;
}

/** Every key whose normalised value differs from the baseline. */
export function diffPayload(
  current: WorkspaceSettingsFormState,
  baseline: WorkspaceSettingsFormState
): Partial<WorkspaceSettingsFormState> {
  const changes: Record<string, unknown> = {};
  for (const key of FIELD_KEYS) {
    if (current[key] !== baseline[key]) changes[key] = current[key];
  }
  return changes as Partial<WorkspaceSettingsFormState>;
}

/**
 * The diff a single section is allowed to send.
 *
 * The point is the negative: Branding saves ten colours and a switch and
 * nothing else. One 784-line form used to PATCH every field it held, so
 * renaming a workspace recorded a full rewrite of its palette, its domain and
 * its SEO text in the audit trail.
 */
export function sectionPayload(
  section: WorkspaceRecordSectionKey,
  current: WorkspaceSettingsFormState,
  baseline: WorkspaceSettingsFormState
): Partial<WorkspaceSettingsFormState> {
  const diff = diffPayload(buildPayload(current), buildPayload(baseline)) as Record<
    string,
    unknown
  >;
  const scoped: Record<string, unknown> = {};
  for (const key of FIELD_KEYS) {
    if (FIELD_DEFS[key].section === section && key in diff) scoped[key] = diff[key];
  }
  return scoped as Partial<WorkspaceSettingsFormState>;
}
