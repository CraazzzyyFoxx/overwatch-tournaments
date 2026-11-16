"use client";

import type { CareerAccount, CareerProfile } from "@/types/user.types";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import { HandleLabel } from "@/components/HandleLabel";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { PageStateCard } from "@/components/ui/page-state-card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import { useFormatter } from "@/lib/datetime/client";
import type { SlotProps } from "@/disciplines/types";

import CareerHeroes from "./CareerHeroes";
import CareerRanks from "./CareerRanks";
import { CareerKpis, CareerRoles } from "./CareerStats";
import CareerVsTournaments from "./CareerVsTournaments";
import { accountState, defaultPlatform, hasCareerData, platformsOf, primaryFirst, queueOf } from "./career-model";
import { useCareer } from "./use-career";

const DOT_TONE = { ok: "success", primary: "success", private: "warning", notFound: "warning", error: "warning", pending: "neutral" } as const;

function GameProfile({ profile }: Readonly<{ profile: CareerProfile }>) {
  const t = useTranslations("users.career.profile");
  const format = useFormatter();
  const [now] = useState(() => Date.now());
  const name = profile.display_name ?? "";
  return (
    <CardSurface title={t("title")} className="min-w-0">
      <div className="flex items-center gap-4">
        <Avatar className="size-16">
          {profile.avatar_url ? <AvatarImage src={profile.avatar_url} alt="" /> : null}
          <AvatarFallback>{name.slice(0, 1)}</AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate font-display text-title font-bold text-[color:var(--aqt-fg)]">{name}</span>
          <span className="truncate text-caption text-[color:var(--aqt-fg-muted)]">
            {[
              typeof profile.attrs.title === "string" ? profile.attrs.title : null,
              typeof profile.attrs.endorsement_level === "number"
                ? t("endorsement", { level: profile.attrs.endorsement_level })
                : null
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {profile.upstream_updated_at ? (
            <span className="text-label text-[color:var(--aqt-fg-dim)]">
              {t("updated", { when: format.relativeTime(new Date(profile.upstream_updated_at), now) })}
            </span>
          ) : null}
        </div>
      </div>
    </CardSurface>
  );
}

function CareerSkeleton() {
  return (
    <div aria-busy className="aqt-player flex flex-col gap-3.5">
      <Skeleton className="h-16 w-full rounded-xl" />
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-36 w-full rounded-xl" />
      </div>
      <Skeleton className="h-64 w-full rounded-xl" />
      <Skeleton className="h-96 w-full rounded-xl" />
    </div>
  );
}

/** The game career on the profile: a chip per account, then the selected account's portrait. */
export default function CareerTab({ userId, scope, metadata }: Readonly<SlotProps["careerTab"]>) {
  const t = useTranslations("users.career");
  const discipline = metadata.discipline.code;
  const career = useCareer(userId, discipline);
  const [accountChoice, setAccountChoice] = useState<number | null>(null);
  const [platformChoice, setPlatformChoice] = useState<string | null>(null);
  const [queueChoice, setQueueChoice] = useState<string | null>(null);

  if (career.isPending) return <CareerSkeleton />;
  if (career.isError) {
    return (
      <PageStateCard state="error" description={t("loadError")} onAction={() => void career.refetch()} className="aqt-player" />
    );
  }
  const accounts = primaryFirst(career.data.accounts);
  if (accounts.length === 0) {
    return <PageStateCard state="empty" title={t("empty.title")} description={t("empty.description")} className="aqt-player" />;
  }

  const account: CareerAccount = accounts.find((candidate) => candidate.social_account_id === accountChoice) ?? accounts[0];
  const platforms = platformsOf(account);
  const platform = platformChoice !== null && platforms.includes(platformChoice) ? platformChoice : defaultPlatform(account);
  const competitive = queueOf(account, platform, "competitive");
  const quickplay = queueOf(account, platform, "quickplay");
  const queueKey = queueChoice === "quickplay" && quickplay ? "quickplay" : competitive ? "competitive" : "quickplay";
  const queue = queueKey === "competitive" ? competitive : quickplay;
  const state = accountState(account);
  const unavailable = state === "primary" || state === "ok" ? "noQueues" : state;

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      <ToggleGroup
        variant="card"
        aria-label={t("accounts")}
        value={String(account.social_account_id)}
        onValueChange={(value) => setAccountChoice(Number(value))}
        className="grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
      >
        {accounts.map((candidate) => {
          const candidateState = accountState(candidate);
          return (
            <ToggleGroupItem key={candidate.social_account_id} value={String(candidate.social_account_id)}>
              <HandleLabel handle={candidate.handle} className="text-sm font-semibold text-[color:var(--aqt-fg)]" />
              <span className="flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-dim)]">
                <StatusDot tone={DOT_TONE[candidateState]} />
                {t(`state.${candidateState}`)}
              </span>
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        {account.profile ? <GameProfile profile={account.profile} /> : null}
        {hasCareerData(account) ? (
          <CareerRanks userId={userId} metadata={metadata} accountId={account.social_account_id} platform={platform} framed />
        ) : null}
      </div>

      {!queue ? (
        <EmptyNote tone="neutral" title={t(`unavailable.${unavailable}.title`)}>
          {t(`unavailable.${unavailable}.description`)}
        </EmptyNote>
      ) : (
        <>
          <CardSurface
            title={t("queue.title")}
            action={
              <div className="flex flex-wrap items-center gap-2">
                {platforms.length > 1 && platform ? (
                  <ToggleGroup size="sm" aria-label={t("platform")} value={platform} onValueChange={setPlatformChoice}>
                    {platforms.map((value) => (
                      <ToggleGroupItem key={value} value={value} className="uppercase">
                        {value}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                ) : null}
                {competitive && quickplay ? (
                  <ToggleGroup size="sm" aria-label={t("queue.title")} value={queueKey} onValueChange={setQueueChoice}>
                    <ToggleGroupItem value="competitive">
                      {competitive.season == null ? t("queue.competitive") : t("queue.competitiveSeason", { season: competitive.season })}
                    </ToggleGroupItem>
                    <ToggleGroupItem value="quickplay">{t("queue.quickplay")}</ToggleGroupItem>
                  </ToggleGroup>
                ) : (
                  <span className="text-caption text-[color:var(--aqt-fg-muted)]">
                    {queue.queue === "competitive"
                      ? queue.season == null
                        ? t("queue.competitive")
                        : t("queue.competitiveSeason", { season: queue.season })
                      : t("queue.quickplay")}
                  </span>
                )}
              </div>
            }
            bodyClassName="flex flex-col gap-6"
          >
            <CareerKpis queue={queue} />
            <CareerRoles queue={queue} metadata={metadata} />
          </CardSurface>

          {queue.characters.length > 0 ? (
            <CardSurface title={t("heroes.title")} flush bodyClassName="px-1.5 py-2">
              <CareerHeroes queue={queue} discipline={discipline} />
            </CardSurface>
          ) : null}

          {competitive ? (
            <CareerVsTournaments userId={userId} queue={competitive} discipline={discipline} scope={scope} />
          ) : null}
        </>
      )}

      <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("footer")}</p>
    </div>
  );
}
