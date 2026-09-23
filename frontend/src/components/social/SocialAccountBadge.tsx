import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { getSocialProviderConfig, socialProfileUrl } from "@/lib/social/providers";
import type { SocialAccount } from "@/types/user.types";

import { SocialIcon } from "./SocialIcon";

interface SocialAccountBadgeProps {
  account: SocialAccount;
  /** Wrap in a link to the provider profile when one is derivable (default true). */
  linkify?: boolean;
}

/** A single social identity rendered as a provider-tinted badge with a verified mark. */
export function SocialAccountBadge({ account, linkify = true }: Readonly<SocialAccountBadgeProps>) {
  const t = useTranslations();
  const config = getSocialProviderConfig(account.provider);
  const url = linkify ? socialProfileUrl(account) : null;

  // Tints are built with `color-mix`, not a JS hex parse: `config.color` is an
  // `--aqt-brand-*` token reference that only CSS can resolve. Mixing with
  // `transparent` in srgb is exactly the old `rgba(r, g, b, a)`, so the badge
  // keeps the tint it had when these were literal hex.
  const surface = `color-mix(in srgb, ${config.color} 6.25%, transparent)`;
  const border = `color-mix(in srgb, ${config.color} 25%, transparent)`;
  // Raw brand hues fail WCAG AA as 12.5px label text on our dark surfaces
  // (Discord #5865f2 → 4.04:1, Twitch #9146ff → 4.01:1). The mark keeps the
  // exact brand colour; the *label* is lifted toward white, which reads at
  // 5.4:1+ while staying unmistakably Discord-blurple / Twitch-purple.
  const labelColor = `color-mix(in srgb, ${config.color} 80%, white)`;

  const badge = (
    <span
      className="inline-flex items-center gap-1.5 rounded-[7px] border px-2 py-1 text-caption font-medium"
      style={{
        background: surface,
        borderColor: border,
        color: labelColor
      }}
      title={
        account.is_verified
          ? `${config.label} · ${t("registration.accounts.verified")}`
          : config.label
      }
    >
      <SocialIcon provider={account.provider} size={12} />
      <span>{account.username}</span>
      {account.is_verified ? (
        <Check size={12} aria-label={t("registration.accounts.verified")} />
      ) : null}
    </span>
  );

  if (!url) {
    return badge;
  }
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="no-underline">
      {badge}
    </a>
  );
}
