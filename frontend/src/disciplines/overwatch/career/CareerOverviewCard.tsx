"use client";

import type { CareerQueue } from "@/types/user.types";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { CARD_HEAD_LINK, CardSurface } from "@/components/profile/atoms";
import { useFormatter } from "@/lib/datetime/client";
import type { SlotProps } from "@/disciplines/types";

import { useHeroClass } from "../character/classes";
import CareerRanks from "./CareerRanks";
import { defaultPlatform, mainDataAccount, queueOf } from "./career-model";
import { useCareer, useHeroFaces } from "./use-career";

const MAINS = 6;

/**
 * The overview's compact ladder card: ranks, the competitive and quick-play lines, the season's mains and the role
 * split. Drawn only for a player with an account that has career data; the header link opens the full tab.
 */
export default function CareerOverviewCard({ userId, userSlug, metadata }: Readonly<SlotProps["careerOverview"]>) {
  const t = useTranslations("users.career");
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const discipline = metadata.discipline.code;
  const faceOf = useHeroFaces(discipline);
  const career = useCareer(userId, discipline);
  const account = career.data ? mainDataAccount(career.data.accounts) : undefined;
  if (!account) return null;

  const platform = defaultPlatform(account);
  const competitive = queueOf(account, platform, "competitive");
  const quickplay = queueOf(account, platform, "quickplay");
  const percent = (value: number) => format.number(value, { style: "percent", maximumFractionDigits: 0 });
  const line = (label: string, queue: CareerQueue | undefined) =>
    queue ? (
      <div className="flex items-baseline justify-between gap-3 text-caption">
        <dt className="text-[color:var(--aqt-fg-dim)]">{label}</dt>
        <dd className="aqt-tnum text-[color:var(--aqt-fg-muted)]">
          {[
            t("overview.games", { count: queue.games_played ?? 0 }),
            queue.winrate == null ? null : percent(queue.winrate),
            t("kpi.hoursValue", { hours: format.number(queue.seconds / 3600, { maximumFractionDigits: 1 }) })
          ]
            .filter(Boolean)
            .join(" · ")}
        </dd>
      </div>
    ) : null;
  // Mains of the competitive season; a player with no ranked games shows their quick-play ones.
  const mainsSource = competitive ?? quickplay;
  const mains = [...new Set(mainsSource?.roles.flatMap((role) => role.mains) ?? [])].slice(0, MAINS);

  return (
    <CardSurface
      title={t("overview.title")}
      action={
        <HoverPrefetchLink href={`/users/${userSlug}?tab=ladder`} className={CARD_HEAD_LINK}>
          {t("overview.more")}
          <ArrowRight aria-hidden className="size-3" />
        </HoverPrefetchLink>
      }
      bodyClassName="flex flex-col gap-4"
    >
      <CareerRanks userId={userId} metadata={metadata} accountId={account.social_account_id} platform={platform} compact />
      <dl className="flex flex-col gap-1.5">
        {line(
          competitive?.season == null ? t("queue.competitive") : t("queue.competitiveSeason", { season: competitive.season }),
          competitive
        )}
        {line(t("queue.quickplay"), quickplay)}
      </dl>
      {mains.length > 0 ? (
        <div className="flex items-center gap-2">
          <span className="text-label text-[color:var(--aqt-fg-dim)]">{t("overview.mains")}</span>
          <span className="flex items-center gap-1">
            {mains.map((key) => (
              <CatalogEntityImage key={key} entity={faceOf(key)} size="sm" />
            ))}
          </span>
        </div>
      ) : null}
      {mainsSource && mainsSource.roles.length > 0 ? (
        <p className="aqt-tnum text-caption text-[color:var(--aqt-fg-muted)]">
          {mainsSource.roles.map((role) => `${heroClass.label(role.role)} ${percent(role.share)}`).join(" · ")}
        </p>
      ) : null}
    </CardSurface>
  );
}
