import { Check } from "lucide-react";

import { getSocialProviderConfig, socialProfileUrl } from "@/lib/social-providers";
import type { SocialAccount } from "@/types/user.types";

import { SocialIcon } from "./SocialIcon";

interface SocialAccountBadgeProps {
  account: SocialAccount;
  /** Wrap in a link to the provider profile when one is derivable (default true). */
  linkify?: boolean;
}

/** A single social identity rendered as a provider-tinted badge with a verified mark. */
export function SocialAccountBadge({ account, linkify = true }: SocialAccountBadgeProps) {
  const config = getSocialProviderConfig(account.provider);
  const url = linkify ? socialProfileUrl(account) : null;

  const badge = (
    <span
      className="inline-flex items-center gap-1.5 rounded-[7px] border px-2 py-1 text-[12.5px] font-medium"
      style={{ background: `${config.color}10`, borderColor: `${config.color}40`, color: config.color }}
      title={account.is_verified ? `${config.label} · verified` : config.label}
    >
      <SocialIcon provider={account.provider} size={12} />
      <span>{account.username}</span>
      {account.is_verified ? <Check size={12} aria-label="Verified" /> : null}
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
