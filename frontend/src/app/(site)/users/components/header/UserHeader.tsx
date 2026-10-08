import Image from "next/image";
import { getTranslations } from "next-intl/server";
import { ArrowDown, ArrowUp } from "lucide-react";
import { User, UserProfile } from "@/types/user.types";
import { getSocialProviderConfig, socialProfileUrl, sortSocialAccounts } from "@/lib/social/providers";
import { playerRoleTint } from "@/lib/roster/player-role";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getPlayerImage } from "@/lib/player";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { FormStreak, ProfileStat, type FormResult } from "@/app/(site)/users/components/shared/atoms";
import ProfileToolbar from "@/app/(site)/users/components/header/ProfileToolbar";
import userService from "@/services/user.service";
import { HeroFrame } from "@/components/site/PageHero";
import type { StatsScope } from "@/lib/site/stats-scope";

interface UserHeaderProps {
  profile: UserProfile;
  user: User;
  scope: StatsScope;
}

const formatPlace = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(1);
};

const deriveFormStreak = async (userId: number, scope: StatsScope): Promise<FormResult[]> => {
  try {
    const encounters = await userService.getUserEncounters(
      userId,
      1,
      10,
      "played_at",
      "desc",
      undefined,
      undefined,
      scope
    );
    return encounters.results.slice(0, 10).reverse().map((enc): FormResult => {
      const homePlayers = enc.home_team?.players ?? [];
      const isUserHome = homePlayers.some((p) => p.user_id === userId);
      const userScore = isUserHome ? enc.score.home : enc.score.away;
      const oppScore = isUserHome ? enc.score.away : enc.score.home;
      if (userScore > oppScore) return "W";
      if (userScore < oppScore) return "L";
      return "D";
    });
  } catch {
    return [];
  }
};

const primaryRoleOf = (profile: UserProfile) => {
  if (!profile.roles.length) return null;
  return profile.roles.reduce((best, current) => (current.tournaments > best.tournaments ? current : best));
};

const UserHeader = async ({ profile, user, scope }: UserHeaderProps) => {
  const t = await getTranslations();
  const [name, tag] = user.name.split("#");
  const primaryRole = primaryRoleOf(profile);
  const avatarSrc = getPlayerImage(profile, user);

  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;

  // No seasons in the system — show the trend from the most recent tournament:
  // its map winrate vs the user's career map winrate. One lightweight fetch.
  const lastSummary = profile.tournaments.length
    ? [...profile.tournaments].sort((a, b) => b.id - a.id)[0]
    : null;
  // The form streak and the last-tournament fetch are independent — run them
  // in parallel instead of awaiting sequentially.
  const [formStreak, lastTournament] = await Promise.all([
    deriveFormStreak(user.id, scope),
    lastSummary
      ? userService.getUserTournament(user.id, lastSummary.id).catch(() => null)
      : Promise.resolve(null)
  ]);
  const lastWinrate =
    lastTournament && lastTournament.maps > 0 ? (lastTournament.maps_won / lastTournament.maps) * 100 : null;
  const winrateDelta = lastWinrate !== null && winrate !== null ? lastWinrate - winrate : null;

  // `playerRoleTint` is null only when there is no role at all, so a Flex
  // primary role tints flex instead of falling through to damage.
  const roleTint = playerRoleTint(primaryRole?.role);

  return (
    <HeroFrame className="aqt-player" variant="profile">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-6 px-5 py-5 md:gap-x-6 md:px-8 md:py-7 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-x-10">
        <div className="relative size-[72px] shrink-0 md:size-[104px]">
          <div className="relative h-full w-full overflow-hidden rounded-[14px] border border-[color:var(--aqt-border-2)] md:rounded-[18px]">
            <Image src={avatarSrc} alt={t("users.profile.header.avatarAlt", { name })} fill sizes="104px" className="object-cover" priority />
          </div>
          {primaryRole ? (
            <div
              className="absolute -bottom-2 -right-2"
              title={t("users.profile.header.divisionTitle", {
                role: primaryRole.role,
                division: String(primaryRole.division)
              })}
            >
              <DivisionIcon
                division={primaryRole.division}
                tournamentGrid={primaryRole.division_grid_version}
                width={44}
                height={44}
                className="size-9 md:size-11"
              />
            </div>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="m-0 flex flex-wrap items-baseline gap-x-2.5 gap-y-1 font-onest text-[clamp(26px,4vw,46px)] font-semibold leading-none tracking-[-0.01em] text-[color:var(--aqt-fg)]">
            <span className="min-w-0 truncate" title={name}>{name}</span>
            {tag ? (
              <span className="whitespace-nowrap text-[0.46em] font-medium tracking-[0.02em] text-[color:var(--aqt-fg-faint)]">
                #{tag}
              </span>
            ) : null}
          </h1>
          {primaryRole ? (
            <p className="m-0 inline-flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
              <PlayerRoleIcon
                role={primaryRole.role}
                size={14}
                color={`var(--aqt-${roleTint ?? "damage"})`}
                decorative
              />
              {t("users.profile.header.mainRole", { role: primaryRole.role })}
            </p>
          ) : null}
          {user.social_accounts.length > 0 ? (
            <ul className="m-0 mt-1 flex list-none flex-wrap gap-1.5 p-0">
              {sortSocialAccounts(user.social_accounts).map((account) => {
                const url = socialProfileUrl(account);
                const chip = (
                  <>
                    <SocialIcon provider={account.provider} size={12} decorative />
                    <span className="truncate">{account.username}</span>
                  </>
                );
                const chipClass =
                  "inline-flex max-w-[16rem] items-center gap-1.5 rounded-[7px] border border-[color:var(--aqt-border-2)] px-2 py-1 text-caption font-medium text-[color:var(--aqt-fg-muted)]";
                return (
                  <li key={account.id} title={getSocialProviderConfig(account.provider).label}>
                    {url ? (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`${chipClass} transition-colors hover:border-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-fg)]`}
                      >
                        {chip}
                      </a>
                    ) : (
                      <span className={chipClass}>{chip}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>

        <div className="col-span-full flex min-w-0 flex-col gap-5 lg:col-span-1 lg:items-end">
          <ProfileToolbar
            playerId={user.id}
            card={{
              name,
              tag: tag ?? null,
              role: primaryRole?.role ?? null,
              roleTint,
              division: primaryRole?.division ?? null,
              winrate,
              avgPlacement: profile.avg_placement,
              titles: profile.tournaments_won,
              tournaments: profile.tournaments_count,
              mapsWon: profile.maps_won,
              mapsTotal: profile.maps_total,
              form: formStreak
            }}
          />

          <div className="grid w-full grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:w-auto lg:gap-x-9">
            <ProfileStat
              label={t("users.profile.stats.tournaments")}
              value={profile.tournaments_count}
              sub={
                profile.tournaments_won > 0
                  ? t("users.profile.stats.won", { count: String(profile.tournaments_won) })
                  : null
              }
            />
            <ProfileStat
              label={t("users.profile.stats.winrate")}
              value={winrate !== null ? `${winrate.toFixed(1)}%` : "-"}
              sub={
                winrateDelta !== null ? (
                  <span
                    className="inline-flex items-center gap-0.5"
                    style={{ color: winrateDelta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                    title={t("users.profile.stats.deltaTitle")}
                  >
                    {winrateDelta >= 0 ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />}
                    <span className="sr-only">
                      {winrateDelta >= 0 ? t("users.profile.stats.trendUp") : t("users.profile.stats.trendDown")}
                    </span>
                    {t("users.profile.stats.deltaLastTournament", { value: Math.abs(winrateDelta).toFixed(1) })}
                  </span>
                ) : null
              }
            />
            <ProfileStat
              label={t("users.profile.stats.mapsWon")}
              value={profile.maps_won}
              sub={t("users.profile.stats.ofTotal", { total: String(profile.maps_total) })}
            />
            <ProfileStat
              label={t("users.profile.stats.avgPlace")}
              value={formatPlace(profile.avg_placement)}
              sub={
                profile.avg_playoff_placement !== null
                  ? t("users.profile.stats.playoffs", { place: formatPlace(profile.avg_playoff_placement) })
                  : null
              }
            />
          </div>

          <div className="flex w-full flex-wrap items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
            <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
              {t("users.profile.header.formLast", { count: String(formStreak.length) })}
            </span>
            {formStreak.length > 0 ? (
              <FormStreak results={formStreak} />
            ) : (
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">{t("users.profile.header.noRecentMatches")}</span>
            )}
          </div>
        </div>
      </div>
    </HeroFrame>
  );
};

export default UserHeader;
