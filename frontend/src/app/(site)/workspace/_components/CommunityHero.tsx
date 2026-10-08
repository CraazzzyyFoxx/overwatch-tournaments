import { Suspense } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { ArrowRight, ArrowUpRight, ChartColumn, Globe, TriangleAlert } from "lucide-react";

import { HeroFrame } from "@/components/site/PageHero";
import { owtButton } from "@/components/site/owt-button";
import { EYEBROW_CLASS, HERO_TITLE_SIZE_CLASS, LEDE_CLASS } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { TrustedBadge } from "@/components/workspace/TrustedBadge";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { getFormatter } from "@/lib/datetime/server";
import { tournamentHref } from "@/lib/tournament/url";
import type { Workspace } from "@/types/workspace.types";

import { getCommunityTournament, getFirstTournamentYear } from "./community.data";
import { WorkspaceScopeLink } from "./WorkspaceScopeLink";

const CHIP_CLASS =
  "inline-flex min-h-9 items-center gap-2 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 text-caption text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]";

/** The community's public links, in the order the mock shows them. */
function communityLinks(workspace: Workspace) {
  return [
    { key: "discord" as const, url: workspace.discord_url, img: "/discord-white.svg" },
    { key: "twitch" as const, url: workspace.twitch_url, img: "/twitch.png" },
    { key: "boosty" as const, url: workspace.boosty_url, img: "/boosty.svg" }
  ].filter((link): link is typeof link & { url: string } => Boolean(link.url));
}

/** The verified custom domain, the only address shown to people. */
function publicHost(workspace: Workspace): string | null {
  return workspace.custom_domain && workspace.custom_domain_verified_at
    ? workspace.custom_domain
    : null;
}

/**
 * The page's top block: where the visitor is (platform host only), the
 * "on review" notice, and the community's identity hero.
 */
export async function CommunityTop({
  workspace,
  ownHost
}: Readonly<{ workspace: Workspace; ownHost: boolean }>) {
  const t = await getTranslations("workspace");
  const host = publicHost(workspace);

  return (
    <div className="grid gap-7">
      {ownHost ? null : (
        <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
          <Link
            href="/#directory"
            prefetch={false}
            className="inline-flex min-h-9 items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg)]"
          >
            <ArrowRight className="size-3.5 -scale-x-100" aria-hidden />
            {t("backToCommunities")}
          </Link>
          {host ? (
            <a
              href={`https://${host}`}
              target="_blank"
              rel="noopener noreferrer"
              className={`${CHIP_CLASS} max-w-full`}
            >
              <Globe className="size-3.5 shrink-0" aria-hidden />
              <span className="shrink-0">{t("communitySite")}</span>
              <b className="truncate font-medium text-[color:var(--aqt-fg)]">{host}</b>
              <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />
            </a>
          ) : null}
        </div>
      )}

      {workspace.verification_status === "unverified" ? (
        <div
          role="status"
          className="flex gap-3 rounded-xl border border-[color:color-mix(in_srgb,var(--aqt-amber)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_8%,transparent)] px-4 py-3.5"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-body text-[color:var(--aqt-fg-muted)]">
            <b className="font-semibold text-[color:var(--aqt-fg)]">{t("unverifiedTitle")}</b>{" "}
            {t("unverifiedText")}
          </p>
        </div>
      ) : null}

      <HeroFrame>
        <div className="p-[clamp(24px,3.2vw,44px)]">
          <div className="flex items-center gap-[18px] max-[639px]:items-start">
            <WorkspaceAvatar
              workspace={workspace}
              size={72}
              className="max-[639px]:!size-12 max-[639px]:!rounded-xl max-[639px]:!text-base"
            />
            <div className="min-w-0">
              <Suspense fallback={<Skeleton className="h-3 w-44" />}>
                <HeroEyebrow workspace={workspace} />
              </Suspense>
              <h1
                id="ws-title"
                className={`mt-1.5 flex items-center gap-2.5 font-display ${HERO_TITLE_SIZE_CLASS} font-semibold leading-[1.03] tracking-[-0.01em] [overflow-wrap:anywhere]`}
              >
                {workspace.name}
                <TrustedBadge
                  status={workspace.verification_status}
                  className="size-[22px] shrink-0"
                />
              </h1>
            </div>
          </div>

          {workspace.description ? (
            <p className={`${LEDE_CLASS} mt-[18px]`}>{workspace.description}</p>
          ) : null}

          {communityLinks(workspace).length > 0 ? (
            <div className="mt-[18px] flex flex-wrap gap-2">
              {communityLinks(workspace).map((link) => (
                <a
                  key={link.key}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={CHIP_CLASS}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- local brand mark, fixed 16px */}
                  <img src={link.img} alt="" width={16} height={16} className="size-4 object-contain" />
                  {t(`links.${link.key}`)}
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </a>
              ))}
            </div>
          ) : null}

          <Suspense fallback={<HeroCtaSkeleton />}>
            <HeroCta workspace={workspace} />
          </Suspense>
        </div>
      </HeroFrame>
    </div>
  );
}

/** "С 2019 года · <слоган>" — the year the community started running events. */
async function HeroEyebrow({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations("workspace");
  let year: number | null = null;
  try {
    year = await getFirstTournamentYear(workspace.id);
  } catch {
    // No history read, no "since" line — the name below carries the block.
  }

  const since = year === null ? null : t("since", { year });
  const parts = [since, workspace.tagline].filter(Boolean);
  if (parts.length === 0) return null;

  return <p className={EYEBROW_CLASS}>{parts.join(" · ")}</p>;
}

function HeroCtaSkeleton() {
  return (
    <div className="mt-[26px] flex flex-wrap gap-2.5">
      <Skeleton className="h-11 w-40 rounded-[var(--aqt-radius-sm)]" />
      <Skeleton className="h-11 w-36 rounded-[var(--aqt-radius-sm)]" />
    </div>
  );
}

/**
 * The page's single primary action: enter the open tournament if there is one,
 * otherwise browse the community's tournaments.
 */
async function HeroCta({ workspace }: Readonly<{ workspace: Workspace }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);

  let tournament = null;
  try {
    tournament = await getCommunityTournament(workspace.id);
  } catch {
    // Fall through to the browse actions: a failed read must not hide the page.
  }
  const registration = tournament?.status === "registration" ? tournament : null;
  const registrationEnd =
    registration?.phase_schedule.find((phase) => phase.status === "registration")?.ends_at ?? null;

  return (
    <>
      <div className="mt-[26px] flex flex-wrap gap-2.5">
        {registration ? (
          <>
            <Link
              href={tournamentHref(registration)}
              prefetch={false}
              aria-label={t("applyTo", { name: registration.name })}
              className={owtButton({ variant: "primary", size: "lg" })}
            >
              {t("apply")}
            </Link>
            <WorkspaceScopeLink
              workspaceId={workspace.id}
              href="/tournaments"
              className={owtButton({ variant: "outline", size: "lg" })}
            >
              {t("allTournaments")}
            </WorkspaceScopeLink>
          </>
        ) : (
          <>
            <WorkspaceScopeLink
              workspaceId={workspace.id}
              href="/tournaments"
              className={owtButton({ variant: "primary", size: "lg" })}
            >
              {t("allTournaments")}
            </WorkspaceScopeLink>
            <WorkspaceScopeLink
              workspaceId={workspace.id}
              href="/statistics"
              className={owtButton({ variant: "outline", size: "lg" })}
            >
              <ChartColumn aria-hidden />
              {t("statistics")}
            </WorkspaceScopeLink>
          </>
        )}
      </div>
      {registration ? (
        <p className="mt-2.5 text-caption text-[color:var(--aqt-fg-dim)]">
          {registration.name}
          {registrationEnd ? (
            <>
              {" · "}
              {t("acceptingUntil")}{" "}
              <time dateTime={registrationEnd}>
                {format.dateTime(new Date(registrationEnd), {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit"
                })}
              </time>
            </>
          ) : null}
          {typeof registration.registrations_count === "number"
            ? ` · ${t("applications", { count: registration.registrations_count })}`
            : null}
        </p>
      ) : null}
    </>
  );
}
