import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig, socialAccountLabel, sortSocialAccounts } from "@/lib/social/providers";
import type { SocialAccount } from "@/types/user.types";

/**
 * A player's social identities, provider-ordered, as text: the brand mark, the
 * handle and, when proven, a verified mark. A handle is a fact, not a chip
 * (DESIGN.md §4), so nothing here is boxed or tinted.
 */
export function SocialAccountList({ accounts }: Readonly<{ accounts: SocialAccount[] | undefined }>) {
  const t = useTranslations();
  if (!accounts || accounts.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-caption">
      {sortSocialAccounts(accounts).map((account) => (
        <li
          key={account.id}
          className="inline-flex min-w-0 items-center gap-1.5"
          title={[getSocialProviderConfig(account.provider).label, account.display_name ? account.username : null]
            .filter(Boolean)
            .join(" · ")}
        >
          <SocialIcon provider={account.provider} size={12} className="shrink-0" />
          <span className="truncate">{socialAccountLabel(account)}</span>
          {account.is_verified ? (
            <StatusIcon icon={Check} label={t("registration.accounts.verified")} variant="success" className="size-3" />
          ) : null}
        </li>
      ))}
    </ul>
  );
}
