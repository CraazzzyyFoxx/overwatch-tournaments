"use client";

import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import { tierAt } from "@/components/rank/rank-history-model";
import Image from "@/components/ui/image";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { CurrentRank } from "@/types/rank.types";

import { useHeroClass } from "../character/classes";
import { useCurrentRanks } from "./use-career";

/**
 * The player's current rank per role on one platform: the existing current-ranks read, emblems from the game's
 * native ladder. Each role carries the season it was last ranked in, which can lag the current one.
 */
export default function CareerRanks({
  userId,
  metadata,
  accountId,
  platform,
  compact = false,
  framed = false
}: Readonly<{
  userId: number;
  metadata: DisciplineMetadata;
  accountId: number;
  platform: string | null;
  /** Emblems stacked over their text, for a narrow column. */
  compact?: boolean;
  /** Wrapped in the profile's section card, drawn only when there is a rank to show. */
  framed?: boolean;
}>) {
  const t = useTranslations("users.career");
  const heroClass = useHeroClass(metadata);
  const ranks = useCurrentRanks(userId, metadata.discipline.code);
  if (!ranks.data) return null;

  const order = metadata.roles.filter((role) => role.parent_id === null).sort((a, b) => a.sort_order - b.sort_order);
  const byRole = new Map<string, CurrentRank>(
    ranks.data.ranks
      .filter((rank) => rank.social_account_id === accountId && (rank.platform ?? null) === platform && rank.role)
      .map((rank) => [rank.role as string, rank])
  );
  const lines = order.filter((role) => byRole.has(role.code));
  if (lines.length === 0) return null;

  const list = (
    <dl aria-label={t("rank.title")} className={compact ? "grid grid-cols-3 gap-3" : "grid grid-cols-1 gap-4 sm:grid-cols-3"}>
      {lines.map((role) => {
        const rank = byRole.get(role.code) as CurrentRank;
        const ranked = rank.is_ranked && rank.rank_value != null;
        const tier = ranked ? tierAt(metadata.native_ladder, rank.rank_value) : undefined;
        return (
          <div key={role.code} className={compact ? "flex flex-col items-center gap-1 text-center" : "flex items-center gap-3"}>
            {tier ? (
              <Image src={tier.icon_url} alt="" aria-hidden width={44} height={44} className="size-11 shrink-0 object-contain" />
            ) : (
              <div aria-hidden className="size-11 shrink-0 rounded-full border border-dashed border-[color:var(--aqt-border-2)]" />
            )}
            <div className="min-w-0">
              <dt className="flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)]">
                {heroClass.icon(role.code, 14)}
                {heroClass.label(role.code)}
              </dt>
              <dd className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]">
                {tier?.name ?? rank.division ?? t("rank.unranked")}
              </dd>
              {rank.season != null ? (
                <dd className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">{t("season", { season: rank.season })}</dd>
              ) : null}
            </div>
          </div>
        );
      })}
    </dl>
  );
  return framed ? <CardSurface title={t("rank.title")}>{list}</CardSurface> : list;
}
