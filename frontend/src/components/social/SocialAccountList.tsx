import { sortSocialAccounts } from "@/lib/social-providers";
import type { SocialAccount } from "@/types/user.types";

import { SocialAccountBadge } from "./SocialAccountBadge";

interface SocialAccountListProps {
  accounts: SocialAccount[] | undefined;
  linkify?: boolean;
  className?: string;
}

/** Renders a player's social identities as provider-ordered badges. */
export function SocialAccountList({ accounts, linkify = true, className }: SocialAccountListProps) {
  if (!accounts || accounts.length === 0) {
    return null;
  }
  return (
    <div className={className ?? "flex flex-wrap gap-1.5"}>
      {sortSocialAccounts(accounts).map((account) => (
        <SocialAccountBadge key={account.id} account={account} linkify={linkify} />
      ))}
    </div>
  );
}
