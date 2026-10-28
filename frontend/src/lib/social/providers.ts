import type { SocialAccount, SocialProvider } from "@/types/user.types";

/**
 * Unified catalog of social providers + helpers. Single source of truth for
 * how a player social identity is labelled, iconned, coloured, ordered and
 * linked across the app — display badges, the admin manager and the merge UI
 * all read from here instead of hard-coding per-provider branches.
 */

export interface SocialProviderConfig {
  /** Canonical provider key (matches backend `social_account.provider`). */
  value: string;
  label: string;
  /** Public icon path, or null when there is no brand image (falls back to a glyph). */
  icon: string | null;
  /** Brand accent colour as a CSS value (an `--aqt-brand-*` token reference).
   *  Consumed only in CSS — inline styles and `color-mix` — never parsed in JS,
   *  so a `var()` reference is safe here. See `SocialIcon`. */
  color: string;
  /** Input placeholder for the admin add/edit form. */
  placeholder: string;
  /** Build a public profile URL from the handle, when the provider has one. */
  profileUrl?: (username: string) => string | null;
  /** Whether ownership of a handle can be proven (`social_account.is_verified`) —
   *  gates the admin "manually verify" action and a form's `require_verified`
   *  toggle. Mirrors backend `ProviderSpec.can_be_verified`. */
  canBeVerified?: boolean;
  /** Whether this is a GAME account. The primary game handle is a registration's
   *  public identity. Mirrors `ProviderSpec.is_game_provider`. */
  isGameProvider?: boolean;
  /** Default ceiling on handles of this provider in one registration answer;
   *  `undefined` means one. Mirrors `ProviderSpec.default_max_count`. */
  defaultMaxCount?: number;
  /** Collapse spacing around `#` (only BattleTags also drop inner name spaces
   *  when matched), or read any Steam spelling as its account id. Mirrors
   *  `ProviderSpec.normalize`. */
  normalizeRule?: "battletag" | "riot_id" | "steam_id";
}

/** Display/selection order. */
export const SOCIAL_PROVIDER_ORDER: SocialProvider[] = [
  "battlenet",
  "discord",
  "twitch",
  "boosty",
  "vk",
  "youtube",
  "riot",
  "steam"
];

const SOCIAL_PROVIDER_CONFIG: Record<SocialProvider, SocialProviderConfig> = {
  battlenet: {
    value: "battlenet",
    label: "Battle.net",
    icon: "/battlenet.svg",
    color: "var(--aqt-brand-battlenet)",
    placeholder: "Name#1234",
    canBeVerified: true,
    isGameProvider: true,
    // Smurfs are a normal Overwatch fact, so a registration may carry five.
    defaultMaxCount: 5,
    normalizeRule: "battletag"
  },
  discord: {
    value: "discord",
    label: "Discord",
    icon: "/discord.png",
    color: "var(--aqt-brand-discord)",
    placeholder: "username",
    canBeVerified: true
  },
  twitch: {
    value: "twitch",
    label: "Twitch",
    icon: "/twitch.png",
    color: "var(--aqt-brand-twitch)",
    placeholder: "username",
    profileUrl: (u) => `https://twitch.tv/${encodeURIComponent(u)}`,
    canBeVerified: true
  },
  boosty: {
    value: "boosty",
    label: "Boosty",
    icon: "/boosty.svg",
    color: "var(--aqt-brand-boosty)",
    placeholder: "username",
    profileUrl: (u) => `https://boosty.to/${encodeURIComponent(u)}`
  },
  vk: {
    value: "vk",
    label: "VK",
    icon: null,
    color: "var(--aqt-brand-vk)",
    placeholder: "username",
    profileUrl: (u) => `https://vk.com/${encodeURIComponent(u)}`
  },
  youtube: {
    value: "youtube",
    label: "YouTube",
    icon: null,
    color: "var(--aqt-brand-youtube)",
    placeholder: "@handle",
    profileUrl: (u) => `https://youtube.com/${encodeURIComponent(u)}`
  },
  riot: {
    value: "riot",
    label: "Riot ID",
    icon: "/riot.png",
    color: "var(--aqt-fg-dim)",
    placeholder: "Name#TAG",
    canBeVerified: true,
    isGameProvider: true,
    normalizeRule: "riot_id"
  },
  steam: {
    value: "steam",
    label: "Steam",
    icon: "/steam.svg",
    color: "var(--aqt-fg-dim)",
    placeholder: "76561198000000000",
    profileUrl: (u) => {
      const accountId = steamAccountId(u);
      return accountId == null ? null : `https://steamcommunity.com/profiles/${BigInt(accountId) + STEAM_ID64_BASE}`;
    },
    canBeVerified: true,
    isGameProvider: true,
    normalizeRule: "steam_id"
  }
};

/** Config for any provider string, with a safe fallback for unknown ones. */
export function getSocialProviderConfig(provider: string): SocialProviderConfig {
  return (
    SOCIAL_PROVIDER_CONFIG[provider as SocialProvider] ?? {
      value: provider,
      label: provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "Account",
      icon: null,
      color: "var(--aqt-fg-dim)",
      placeholder: "username"
    }
  );
}

const _providerRank = (provider: string): number => {
  const index = SOCIAL_PROVIDER_ORDER.indexOf(provider as SocialProvider);
  return index === -1 ? SOCIAL_PROVIDER_ORDER.length : index;
};

/** Stable display order: provider order, primary first, then id (mirrors backend). */
export function sortSocialAccounts(accounts: readonly SocialAccount[]): SocialAccount[] {
  return [...accounts].sort(
    (a, b) =>
      _providerRank(a.provider) - _providerRank(b.provider) ||
      Number(b.is_primary) - Number(a.is_primary) ||
      a.id - b.id
  );
}

/** Accounts of a single provider, in display order. */
export function socialAccountsForProvider(accounts: readonly SocialAccount[], provider: string): SocialAccount[] {
  return sortSocialAccounts(accounts.filter((account) => account.provider === provider));
}

/** Public profile URL for an account (provider-derived, else the stored url). */
export function socialProfileUrl(account: SocialAccount): string | null {
  const derived = getSocialProviderConfig(account.provider).profileUrl?.(account.username);
  return derived ?? account.url ?? null;
}

/** What people know an account by: the provider's display name (Steam persona name) over an opaque handle. */
export function socialAccountLabel(account: SocialAccount): string {
  return account.display_name || account.username;
}

/** `\s*#\s*` around a BattleTag's separator, as `shared.core.social` spells it. */
const BATTLE_TAG_HASH = /\s*#\s*/g;

/** The SteamID64 of account id 0: a SteamID64 is this plus the account id. */
const STEAM_ID64_BASE = BigInt("76561197960265728");
const STEAM_ACCOUNT_MAX = BigInt("4294967295");

/**
 * A Steam handle as its decimal account id (SteamID3's `N`, deadlock-api's `account_id`), mirroring
 * `shared.core.social.steam_account_id`: an account id, a SteamID64, `[U:1:N]`, `STEAM_X:Y:Z` (`Z*2+Y`) or a
 * `steamcommunity.com/profiles/<SteamID64>` link. `null` for anything else, a vanity `/id/<name>` link included.
 */
function steamAccountId(handle: string): string | null {
  const text = handle.trim();
  const id64 = /^(?:https?:\/\/steamcommunity\.com\/profiles\/(\d{17})\/?|(\d{17}))$/i.exec(text);
  const id3 = /^(?:\[U:1:(\d{1,10})\]|([1-9]\d{0,9}))$/i.exec(text);
  const legacy = /^STEAM_[0-5]:([01]):(\d{1,10})$/i.exec(text);
  const id = id64
    ? BigInt(id64[1] ?? id64[2]) - STEAM_ID64_BASE
    : id3
      ? BigInt(id3[1] ?? id3[2])
      : legacy
        ? BigInt(legacy[2]) * BigInt(2) + BigInt(legacy[1])
        : null;
  return id != null && id >= 1 && id <= STEAM_ACCOUNT_MAX ? id.toString() : null;
}

/**
 * The handle as STORED, mirroring `shared.core.social.display_social_handle`:
 * trimmed, casing kept; a BattleTag or Riot ID additionally loses the spacing
 * a human types around `#` (`Player # 1234` → `Player#1234`), and a Steam
 * handle becomes its account id.
 */
export function displaySocialHandle(provider: string, handle: string): string {
  const text = handle.trim();
  const rule = getSocialProviderConfig(provider).normalizeRule;
  if (rule === "steam_id") return steamAccountId(text) ?? text;
  return hasTaggedHandle(provider) ? text.replace(BATTLE_TAG_HASH, "#") : text;
}

/** Whether a provider's handle carries a `#tag` discriminator: a BattleTag or a Riot ID. */
export function hasTaggedHandle(provider: string): boolean {
  const rule = getSocialProviderConfig(provider).normalizeRule;
  return rule === "battletag" || rule === "riot_id";
}

/**
 * The handle as MATCHED, mirroring `shared.core.social.normalize_social_handle`:
 * the display form casefolded, with every remaining space dropped for a
 * BattleTag. This — never the raw input — is what a provider's grammar runs on.
 */
export function normalizeSocialHandle(provider: string, handle: string): string {
  const display = displaySocialHandle(provider, handle);
  return (
    getSocialProviderConfig(provider).normalizeRule === "battletag"
      ? display.replaceAll(" ", "").trim()
      : display
  ).toLowerCase();
}
