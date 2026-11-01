import Image from "@/components/ui/image";
import { getTranslations } from "next-intl/server";
import { ArrowDown, ArrowUp, Check } from "lucide-react";
import { User, UserProfile } from "@/types/user.types";
import {
  getSocialProviderConfig,
  socialAccountLabel,
  socialAccountsForProvider,
  socialProfileUrl,
  sortSocialAccounts
} from "@/lib/social/providers";
import { findRole, registrationRoles, roleName, rolePresentation } from "@/lib/roster/ontology";
import disciplineService from "@/services/discipline.service";
import { SocialIcon } from "@/components/social/SocialIcon";
import { canonicalDisplay, getPlayerImage } from "@/lib/player";
import DivisionIcon from "@/components/DivisionIcon";
import { FormStreak, ProfileStat, type FormResult } from "@/components/profile/atoms";
import ProfileToolbar from "@/app/(site)/users/components/header/ProfileToolbar";
import userService from "@/services/user.service";
import { HeroFrame } from "@/components/site/PageHero";
import { Eyebrow } from "@/components/ui/eyebrow";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import { encounterPerspective } from "@/app/(site)/users/components/shared/encounter-perspective";

interface UserHeaderProps {
  profile: UserProfile;
  user: User;
  scope: StatsScope;
  /** The profile's game, or `null` for the cross-game header (no role, no game metadata). */
  discipline: string | null;
  /** The workspace axis the profile is viewed on: its ontology names the primary role (sub-roles included). */
  axis: WorkspaceAxis;
}

const formatPlace = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(1);
};

const deriveFormStreak = async (
  userId: number,
  discipline: string | null,
  scope: StatsScope
): Promise<FormResult[]> => {
  try {
    // The streak reads each encounter's seats (scores and rosters) only: no matches, no tournament.
    const encounters = await userService.getUserEncounters(
      userId,
      discipline,
      1,
      10,
      "played_at",
      "desc",
      ["teams", "teams.players"],
      undefined,
      scope
    );
    return encounters.results.slice(0, 10).reverse().map((enc): FormResult => {
      const { kind } = encounterPerspective(enc, userId);
      return kind === "win" ? "W" : kind === "loss" ? "L" : "D";
    });
  } catch {
    return [];
  }
};

const primaryRoleOf = (profile: UserProfile) => {
  if (!profile.roles.length) return null;
  return profile.roles.reduce((best, current) => (current.tournaments > best.tournaments ? current : best));
};

const UserHeader = async ({ profile, user, scope, discipline, axis }: UserHeaderProps) => {
  const [t, tRoles] = await Promise.all([getTranslations(), getTranslations("common.roles")]);
  const { name, tag } = canonicalDisplay(user.name);
  const primaryRole = primaryRoleOf(profile);
  const avatarSrc = getPlayerImage(profile, user);

  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;

  // No seasons in the system — show the trend from the most recent tournament:
  // its map winrate vs the user's career map winrate. One lightweight fetch.
  // The server sends the cards newest event first (by date: ids follow creation, not play).
  const lastSummary = profile.tournaments[0] ?? null;
  // The form streak, the last-tournament fetch and the game's metadata are independent — run them
  // in parallel instead of awaiting sequentially.
  const [formStreak, lastTournament, metadata] = await Promise.all([
    deriveFormStreak(user.id, discipline, scope),
    lastSummary
      ? userService.getUserTournament(user.id, lastSummary.id).catch(() => null)
      : Promise.resolve(null),
    discipline === null ? Promise.resolve(null) : disciplineService.metadata(axis, discipline).catch(() => null)
  ]);
  const lastWinrate =
    lastTournament && lastTournament.maps > 0 ? (lastTournament.maps_won / lastTournament.maps) * 100 : null;
  const winrateDelta = lastWinrate !== null && winrate !== null ? lastWinrate - winrate : null;

  // The profile's game names and tints its primary role in the viewed workspace's ontology (so a workspace
  // sub-role resolves; a tenant host reads its own); a role it does not know keeps its code and no tint.
  const roleNode = metadata && primaryRole?.role ? findRole(metadata, primaryRole.role) : null;
  const roleColor = metadata && roleNode ? rolePresentation(metadata.roles, roleNode.id).color : null;
  const roleLabel = primaryRole?.role
    ? roleNode
      ? roleName(roleNode, (code) => (tRoles.has(code as never) ? tRoles(code as never) : null))
      : primaryRole.role.role
    : null;
  // The header hairline's and share card's spectrum is the game's own role colours in declared order.
  const spectrum = metadata
    ? registrationRoles(metadata)
        .map((role) => rolePresentation(metadata.roles, role.id).color)
        .filter((color): color is string => color !== null)
    : [];
  // A single-game profile also names the person by their handle in that game (visible accounts only: the payload
  // already drops hidden ones); "all games" shows the canonical name alone.
  const identityProvider = metadata?.discipline.identity_provider ?? null;
  const gameHandle = identityProvider ? (socialAccountsForProvider(user.social_accounts, identityProvider)[0] ?? null) : null;

  return (
    <HeroFrame className="aqt-player" variant="profile" tint={roleColor ?? undefined} spectrum={spectrum}>
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-6 px-5 py-5 md:gap-x-6 md:px-8 md:py-7 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-x-10">
        <div className="relative size-[72px] shrink-0 md:size-[104px]">
          <div className="relative h-full w-full overflow-hidden rounded-[14px] border border-[color:var(--aqt-border-2)] md:rounded-[18px]">
            <Image src={avatarSrc} alt={t("users.profile.header.avatarAlt", { name })} fill sizes="104px" className="object-cover" priority />
          </div>
          {primaryRole && primaryRole.division != null && discipline !== null ? (
            <div
              className="absolute -bottom-2 -right-2"
              title={t("users.profile.header.divisionTitle", {
                role: roleLabel ?? "",
                division: String(primaryRole.division)
              })}
            >
              <DivisionIcon
                division={primaryRole.division}
                tournamentGrid={primaryRole.division_grid_version}
                discipline={discipline}
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
                {tag}
              </span>
            ) : null}
          </h1>
          {gameHandle ? (
            <p
              className="m-0 truncate text-body text-[color:var(--aqt-fg-faint)]"
              title={[getSocialProviderConfig(gameHandle.provider).label, gameHandle.display_name ? gameHandle.username : null]
                .filter(Boolean)
                .join(" · ")}
            >
              {socialAccountLabel(gameHandle)}
            </p>
          ) : null}
          {user.social_accounts.length > 0 ? (
            <ul className="m-0 mt-1 flex list-none flex-wrap gap-1.5 p-0">
              {sortSocialAccounts(user.social_accounts).map((account) => {
                const url = socialProfileUrl(account);
                const providerLabel = getSocialProviderConfig(account.provider).label;
                const verifiedLabel = t("registration.accounts.verified");
                const chip = (
                  <>
                    <SocialIcon provider={account.provider} size={12} decorative />
                    <span className="truncate">{socialAccountLabel(account)}</span>
                    {account.is_verified ? (
                      <Check size={12} aria-label={verifiedLabel} className="shrink-0 text-[color:var(--aqt-teal)]" />
                    ) : null}
                  </>
                );
                const chipClass =
                  "inline-flex max-w-[16rem] items-center gap-1.5 rounded-[7px] border border-[color:var(--aqt-border-2)] px-2 py-1 text-caption font-medium text-[color:var(--aqt-fg-muted)]";
                return (
                  <li
                    key={account.id}
                    title={[providerLabel, account.display_name ? account.username : null, account.is_verified ? verifiedLabel : null]
                      .filter(Boolean)
                      .join(" · ")}
                  >
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
              role: roleLabel,
              roleColor,
              spectrum,
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
            <Eyebrow>{t("users.profile.header.formLast", { count: String(formStreak.length) })}</Eyebrow>
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
