import { PLATFORM_ZONE } from "@/lib/site/host";
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

const FIELD_DEFS = {
  name: field("general", (ws) => ws.name),
  description: field("general", (ws) => ws.description ?? ""),
  tagline: field("general", (ws) => ws.tagline ?? ""),
  about: field("general", (ws) => ws.about ?? ""),
  discord_url: field("general", (ws) => ws.discord_url ?? ""),
  twitch_url: field("general", (ws) => ws.twitch_url ?? ""),
  boosty_url: field("general", (ws) => ws.boosty_url ?? ""),
  timezone: field("general", (ws) => ws.timezone ?? DEFAULT_WORKSPACE_TIMEZONE),
  // Order is data: `[0]` is the default game for new tournaments, grids and
  // mixes, so a drag that only reorders is a real change.
  disciplines_enabled: field("general", (ws) => ws.disciplines_enabled),
  achievement_eval_mode: field("general", (ws) => ws.achievement_eval_mode ?? "live"),

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
function buildPayload(form: WorkspaceSettingsFormState): WorkspaceSettingsFormState {
  const payload = { ...form } as Record<WorkspaceFieldKey, unknown>;
  for (const key of FIELD_KEYS) {
    const { wire } = FIELD_DEFS[key];
    // `wire` is a union of per-field normalisers; the key it is read under is
    // the key its value comes from, which the indexed access cannot express.
    if (wire) payload[key] = (wire as (value: unknown) => unknown)(form[key]);
  }
  return payload as WorkspaceSettingsFormState;
}

/** Every key whose normalised value differs from the baseline (by value: one field is an array). */
function diffPayload(
  current: WorkspaceSettingsFormState,
  baseline: WorkspaceSettingsFormState
): Partial<WorkspaceSettingsFormState> {
  const changes: Record<string, unknown> = {};
  for (const key of FIELD_KEYS) {
    if (JSON.stringify(current[key]) !== JSON.stringify(baseline[key])) changes[key] = current[key];
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

// ─── Validation ───────────────────────────────────────────────────────────────
//
// Each rule mirrors the server's, so a value is refused while it is typed
// rather than on save, with the field named. The server stays the authority:
// a rule here that drifts looser only moves the refusal back to the save bar.

/** `_LINK_HOSTS` in app-service `schemas/workspace.py`: https, the service's own host. */
export const LINK_HOSTS = {
  discord_url: ["discord.gg", "discord.com"],
  twitch_url: ["twitch.tv"],
  boosty_url: ["boosty.to"]
} as const satisfies Partial<Record<WorkspaceFieldKey, readonly string[]>>;

/** `RESERVED_SUBDOMAINS` in `shared/tenancy/hostnames.py`. */
const RESERVED_SUBDOMAINS = new Set([
  "www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws"
]);

/** `_DOMAIN_RE` in `shared/tenancy/hostnames.py`: a multi-label FQDN. */
const DOMAIN_RE =
  /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** What is wrong with a value, as a message key under `workspaceSettings.errors`. */
export type FieldIssue =
  | { key: "nameRequired" }
  | { key: "tooLong"; values: { max: number } }
  | { key: "link"; values: { hosts: string } }
  | { key: "hex" }
  | { key: "subdomainLength" }
  | { key: "subdomainHyphen" }
  | { key: "subdomainReserved"; values: { label: string } }
  | { key: "domain" }
  | { key: "domainPlatform"; values: { zone: string } };

const tooLong = (value: string, max: number): FieldIssue | null =>
  value.length > max ? { key: "tooLong", values: { max } } : null;

function linkIssue(field: keyof typeof LINK_HOSTS, value: string): FieldIssue | null {
  const url = value.trim();
  if (!url) return null;
  const hosts: readonly string[] = LINK_HOSTS[field];
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" && hosts.includes(parsed.hostname.replace(/^www\./, ""))) {
      return tooLong(url, 512);
    }
  } catch {
    // Not a URL at all: the same answer as the wrong host.
  }
  return { key: "link", values: { hosts: hosts.join(" / ") } };
}

const hexIssue = (value: string | null): FieldIssue | null =>
  value?.trim() && !HEX_RE.test(value.trim()) ? { key: "hex" } : null;

/** `validate_subdomain_label`; blank means "no subdomain" and is fine. */
function subdomainIssue(value: string | null): FieldIssue | null {
  const label = value?.trim().toLowerCase() ?? "";
  if (!label) return null;
  if (label.length > 63) return { key: "subdomainLength" };
  if (label.startsWith("-") || label.endsWith("-")) return { key: "subdomainHyphen" };
  if (RESERVED_SUBDOMAINS.has(label)) return { key: "subdomainReserved", values: { label } };
  return null;
}

/** `normalize_custom_domain`, for the custom-domain draft outside the form. */
export function customDomainIssue(value: string): FieldIssue | null {
  const domain = value.trim().toLowerCase().split(":", 1)[0].replace(/\.+$/, "");
  if (!domain || !domain.includes(".") || !DOMAIN_RE.test(domain)) return { key: "domain" };
  if (domain === PLATFORM_ZONE || domain.endsWith(`.${PLATFORM_ZONE}`)) {
    return { key: "domainPlatform", values: { zone: PLATFORM_ZONE } };
  }
  return null;
}

const RULES: {
  [K in WorkspaceFieldKey]?: (value: WorkspaceSettingsFormState[K]) => FieldIssue | null;
} = {
  name: (value) => (value.trim() ? tooLong(value.trim(), 255) : { key: "nameRequired" }),
  tagline: (value) => tooLong(value.trim(), 120),
  about: (value) => tooLong(value.trim(), 4000),
  discord_url: (value) => linkIssue("discord_url", value),
  twitch_url: (value) => linkIssue("twitch_url", value),
  boosty_url: (value) => linkIssue("boosty_url", value),
  brand_primary: hexIssue,
  brand_secondary: hexIssue,
  brand_background: hexIssue,
  brand_surface: hexIssue,
  brand_accent: hexIssue,
  brand_foreground: hexIssue,
  brand_muted: hexIssue,
  brand_border: hexIssue,
  brand_ring: hexIssue,
  brand_destructive: hexIssue,
  subdomain: subdomainIssue
};

/** Every field of `form` the server would refuse, and why. */
export function formIssues(
  form: WorkspaceSettingsFormState
): Partial<Record<WorkspaceFieldKey, FieldIssue>> {
  const issues: Partial<Record<WorkspaceFieldKey, FieldIssue>> = {};
  for (const key of FIELD_KEYS) {
    const rule = RULES[key] as ((value: unknown) => FieldIssue | null) | undefined;
    const issue = rule?.(form[key]);
    if (issue) issues[key] = issue;
  }
  return issues;
}
