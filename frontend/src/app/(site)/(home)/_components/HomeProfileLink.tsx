"use client";

import Link from "next/link";
import { User } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import { getAuthProfileHref } from "@/lib/auth/profile-links";

/** Secondary text link under the hero's search row (mock `.text-link`). */
export const TEXT_LINK_CLASS =
  "inline-flex min-h-11 items-center gap-2 rounded-sm text-body text-[color:var(--aqt-fg-muted)] transition-colors duration-150 hover:text-[color:var(--aqt-fg)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[color:var(--aqt-teal)] [&_svg]:size-4 [&_svg]:text-[color:var(--aqt-fg-dim)]";

/**
 * "My profile and statistics" — only for a signed-in account that is linked to
 * a player, because that link is the only thing that gives it a destination.
 * Client-side: the hero itself is static and must not be held back by the
 * session read.
 */
export function HomeProfileLink() {
  const t = useTranslations("home.hero");
  const { user, status } = useAuthProfile();
  const href = status === "authenticated" ? getAuthProfileHref(user ?? undefined) : undefined;
  if (!href) return null;

  return (
    <Link href={href} prefetch={false} className={TEXT_LINK_CLASS}>
      <User aria-hidden />
      {t("myProfile")}
    </Link>
  );
}
