import { BadgeCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * The teal check a `trusted` community carries next to its name. Says what it
 * means on hover and to assistive tech; renders nothing for other tiers.
 */
export function TrustedBadge({
  status,
  className
}: Readonly<{ status: "unverified" | "verified" | "trusted"; className?: string }>) {
  const t = useTranslations("site.trusted");
  if (status !== "trusted") return null;

  return (
    <span title={t("title")} className="inline-flex shrink-0">
      <BadgeCheck
        role="img"
        aria-label={t("label")}
        className={cn("size-4 text-[color:var(--aqt-teal)]", className)}
      />
    </span>
  );
}
