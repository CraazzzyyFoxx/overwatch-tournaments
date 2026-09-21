/**
 * The builtin field keys, mirroring `backend/shared/domain/forms/builtins.py`.
 *
 * A builtin key is a contract between the two sides: the server owns the
 * behaviour (verified accounts, role composition, the BattleTag grammar), the
 * client owns the renderer. This list is what the builder offers and what
 * `isBuiltinKey` refuses to hand a custom field.
 */

import type { Visibility } from "@/types/forms.types";

/** Identity providers a registration may ask for. `battlenet` is deliberately
 *  absent: the BattleTag is its own builtin with its own grammar. */
export const IDENTITY_PROVIDERS = ["discord", "twitch", "boosty", "vk", "youtube"] as const;

export type IdentityProvider = (typeof IDENTITY_PROVIDERS)[number];

const IDENTITY_KEY_PREFIX = "identity_";

/** The answer key an identity field for `provider` is stored under. */
export function identityKey<P extends string>(provider: P): `identity_${P}` {
  return `${IDENTITY_KEY_PREFIX}${provider}`;
}

/** The provider an identity key names, or `null` when the key is not one. */
export function identityProvider(key: string): string | null {
  if (!key.startsWith(IDENTITY_KEY_PREFIX)) return null;
  const provider = key.slice(IDENTITY_KEY_PREFIX.length);
  return (IDENTITY_PROVIDERS as readonly string[]).includes(provider) ? provider : null;
}

/** Spread as a typed tuple rest so `BuiltinFieldKey` stays a union of the ELEVEN
 *  literals. `.map()` alone widens to `string`, and the admin builder localises a
 *  builtin by key against a typed message dictionary, which only accepts the
 *  literals. (Naming that dictionary's namespace here would make the zone
 *  checker read this shared module as needing an admin-only bundle.) */
const IDENTITY_FIELD_KEYS = IDENTITY_PROVIDERS.map(identityKey) as readonly `identity_${IdentityProvider}`[];

export const BUILTIN_FIELD_KEYS = [
  "battle_tag",
  "smurf_tags",
  "roles",
  "stream_pov",
  "public_notes",
  "organizer_notes",
  ...IDENTITY_FIELD_KEYS,
] as const;

export type BuiltinFieldKey = (typeof BUILTIN_FIELD_KEYS)[number];

/** Static membership table — nothing is inserted at runtime. */
const KNOWN: Record<string, true> = Object.fromEntries(
  BUILTIN_FIELD_KEYS.map((key) => [key, true] as const),
);

export function isBuiltinKey(key: string): key is BuiltinFieldKey {
  return KNOWN[key] === true;
}

/**
 * Keys a CUSTOM field may never take, mirroring the schema's rule
 * (`is_builtin_key(key) or key.startswith(IDENTITY_KEY_PREFIX)`).
 *
 * Wider than {@link isBuiltinKey} on purpose: the whole `identity_` prefix is
 * reserved, not just the five providers this build knows, so a question
 * labelled "Identity card" cannot occupy a namespace a later server release
 * means to own. And it does not depend on what the form currently asks —
 * removing the `battle_tag` builtin must not free its key for a custom field
 * the server would then refuse.
 */
export function isReservedFieldKey(key: string): boolean {
  return KNOWN[key] === true || key.startsWith(IDENTITY_KEY_PREFIX);
}

/**
 * The visibility the catalog FIXES for a builtin, mirroring
 * `BuiltinSpec.fixed_visibility`. `null` where the organizer may choose
 * (`smurf_tags` and the identities).
 *
 * The builder reads this to DISABLE the visibility selector rather than let an
 * organizer pick a value the schema validator would reject.
 */
const FIXED_VISIBILITY: Record<string, Visibility> = {
  battle_tag: "public",
  roles: "public",
  stream_pov: "public",
  public_notes: "public",
  organizer_notes: "organizers",
};

export function builtinFixedVisibility(key: string): Visibility | null {
  return FIXED_VISIBILITY[key] ?? null;
}

/** Which params editor a builtin needs, or `null` when it takes no params. */
export type BuiltinParamsKind = "battle_tag" | "identity" | "roles";

export function builtinParamsKind(key: string): BuiltinParamsKind | null {
  if (key === "battle_tag") return "battle_tag";
  if (key === "roles") return "roles";
  return identityProvider(key) ? "identity" : null;
}
