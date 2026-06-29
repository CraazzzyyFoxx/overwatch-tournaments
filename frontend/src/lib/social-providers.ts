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
  /** Brand accent colour (hex) used for the badge tint. */
  color: string;
  /** Input placeholder for the admin add/edit form. */
  placeholder: string;
  /** Build a public profile URL from the handle, when the provider has one. */
  profileUrl?: (username: string) => string;
}

/** Display/selection order. */
export const SOCIAL_PROVIDER_ORDER: SocialProvider[] = [
  "battlenet",
  "discord",
  "twitch",
  "boosty",
  "vk",
  "youtube"
];

export const SOCIAL_PROVIDER_CONFIG: Record<SocialProvider, SocialProviderConfig> = {
  battlenet: { value: "battlenet", label: "Battle.net", icon: "/battlenet.svg", color: "#148EFF", placeholder: "Name#1234" },
  discord: { value: "discord", label: "Discord", icon: "/discord.png", color: "#5865F2", placeholder: "username" },
  twitch: {
    value: "twitch",
    label: "Twitch",
    icon: "/twitch.png",
    color: "#9146FF",
    placeholder: "username",
    profileUrl: (u) => `https://twitch.tv/${encodeURIComponent(u)}`
  },
  boosty: {
    value: "boosty",
    label: "Boosty",
    icon: null,
    color: "#F15F2C",
    placeholder: "username",
    profileUrl: (u) => `https://boosty.to/${encodeURIComponent(u)}`
  },
  vk: { value: "vk", label: "VK", icon: null, color: "#0077FF", placeholder: "username", profileUrl: (u) => `https://vk.com/${encodeURIComponent(u)}` },
  youtube: { value: "youtube", label: "YouTube", icon: null, color: "#FF0000", placeholder: "@handle", profileUrl: (u) => `https://youtube.com/${encodeURIComponent(u)}` }
};

/** Config for any provider string, with a safe fallback for unknown ones. */
export function getSocialProviderConfig(provider: string): SocialProviderConfig {
  return (
    SOCIAL_PROVIDER_CONFIG[provider as SocialProvider] ?? {
      value: provider,
      label: provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "Account",
      icon: null,
      color: "#8B8B8B",
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

/** Whether the player has any OAuth-verified social account. */
export function hasVerifiedSocial(accounts: readonly SocialAccount[]): boolean {
  return accounts.some((account) => account.is_verified);
}
