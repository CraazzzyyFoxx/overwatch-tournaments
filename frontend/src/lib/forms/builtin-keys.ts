/**
 * The builtin field keys, mirroring `backend/shared/domain/forms/builtins.py`.
 *
 * A builtin key is a contract between the two sides: the server owns the
 * behaviour (verified accounts, role composition, the BattleTag grammar), the
 * client owns the renderer. This list is what the builder offers and what
 * `isBuiltinKey` refuses to hand a custom field.
 */

/** Identity providers a registration may ask for. `battlenet` is deliberately
 *  absent: the BattleTag is its own builtin with its own grammar. */
export const IDENTITY_PROVIDERS = ["discord", "twitch", "boosty", "vk", "youtube"] as const;

export type IdentityProvider = (typeof IDENTITY_PROVIDERS)[number];

const IDENTITY_KEY_PREFIX = "identity_";

/** The answer key an identity field for `provider` is stored under. */
export function identityKey(provider: string): string {
  return IDENTITY_KEY_PREFIX + provider;
}

/** The provider an identity key names, or `null` when the key is not one. */
export function identityProvider(key: string): string | null {
  if (!key.startsWith(IDENTITY_KEY_PREFIX)) return null;
  const provider = key.slice(IDENTITY_KEY_PREFIX.length);
  return (IDENTITY_PROVIDERS as readonly string[]).includes(provider) ? provider : null;
}

export const BUILTIN_FIELD_KEYS = [
  "battle_tag",
  "smurf_tags",
  "roles",
  "stream_pov",
  "public_notes",
  "organizer_notes",
  ...IDENTITY_PROVIDERS.map(identityKey),
] as const;

/** Static membership table — nothing is inserted at runtime. */
const KNOWN: Record<string, true> = Object.fromEntries(
  BUILTIN_FIELD_KEYS.map((key) => [key, true] as const),
);

export function isBuiltinKey(key: string): boolean {
  return KNOWN[key] === true;
}
