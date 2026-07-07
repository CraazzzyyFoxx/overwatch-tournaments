import React from "react";
import Image from "next/image";
import Link from "next/link";
import { User, UserProfile } from "@/types/user.types";
import { hasVerifiedSocial } from "@/lib/social-providers";
import { SocialAccountList } from "@/components/social/SocialAccountList";
import { getPlayerImage } from "@/utils/player";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { FormStreak, type FormResult } from "@/app/(site)/users/components/shared/atoms";
import ProfileToolbar from "@/app/(site)/users/components/header/ProfileToolbar";
import userService from "@/services/user.service";
import { HeroFrame } from "@/components/site/PageHero";

export interface UserHeaderProps {
  profile: UserProfile;
  user: User;
}

const formatPlace = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(1);
};

const deriveFormStreak = async (userId: number): Promise<FormResult[]> => {
  try {
    const encounters = await userService.getUserEncounters(userId, 1, 10, "id", "desc");
    return encounters.results.slice(0, 10).map((enc): FormResult => {
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

const UserHeader = async ({ profile, user }: UserHeaderProps) => {
  const [name, tag] = user.name.split("#");
  const primaryRole = primaryRoleOf(profile);
  const avatarSrc = getPlayerImage(profile, user);

  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;

  // No seasons in the system — show the trend from the most recent tournament:
  // its map winrate vs the user's career map winrate. One lightweight fetch.
  const lastSummary = profile.tournaments.length
    ? [...profile.tournaments].sort((a, b) => (b.number ?? 0) - (a.number ?? 0))[0]
    : null;
  // The form streak and the last-tournament fetch are independent — run them
  // in parallel instead of awaiting sequentially.
  const [formStreak, lastTournament] = await Promise.all([
    deriveFormStreak(user.id),
    lastSummary
      ? userService.getUserTournament(user.id, lastSummary.id).catch(() => null)
      : Promise.resolve(null)
  ]);
  const lastWinrate =
    lastTournament && lastTournament.maps > 0 ? (lastTournament.maps_won / lastTournament.maps) * 100 : null;
  const winrateDelta = lastWinrate !== null && winrate !== null ? lastWinrate - winrate : null;

  const roleSwatchColor =
    primaryRole?.role === "Tank"
      ? "var(--aqt-tank)"
      : primaryRole?.role === "Support"
        ? "var(--aqt-support)"
        : "var(--aqt-damage)";

  return (
    <HeroFrame className="aqt-player">
      <div className="flex items-center justify-between gap-3 px-9 pt-5">
        <p className="m-0 text-[12px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          <Link href="/users" className="hover:text-[color:var(--aqt-fg-muted)]">Users</Link>
          <span className="mx-1">·</span>
          <span className="text-[color:var(--aqt-fg-muted)]">{name}</span>
        </p>
        <ProfileToolbar />
      </div>

      <div className="grid items-center gap-8 p-7 pt-6 md:grid-cols-[auto_1fr_auto] md:px-9 md:py-7">
        <div className="relative h-[110px] w-[110px] flex-shrink-0">
          <div
            className="absolute -inset-1 rounded-[22px] opacity-40 blur-2xl"
            style={{ background: "var(--aqt-teal)" }}
          />
          <div className="relative h-full w-full overflow-hidden rounded-[18px] border border-[color:var(--aqt-border-2)]">
            <Image src={avatarSrc} alt={`${name} avatar`} fill sizes="110px" className="object-cover" priority />
          </div>
          {primaryRole ? (
            <div
              className="absolute -bottom-2 -right-2"
              title={`${primaryRole.role} · Div ${primaryRole.division}`}
            >
              <DivisionIcon
                division={primaryRole.division}
                tournamentGrid={primaryRole.division_grid_version}
                width={46}
                height={46}
              />
            </div>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="aqt-hero-title m-0 flex flex-wrap items-baseline gap-2.5 text-[clamp(28px,4vw,48px)] font-onest font-semibold tracking-[-0.01em] leading-none">
            <span>{name}</span>
            {tag ? <span className="text-[22px] font-medium tracking-[0.04em] text-[color:var(--aqt-fg-faint)]">#{tag}</span> : null}
            {hasVerifiedSocial(user.social_accounts) ? (
              <span className="text-[18px] text-[color:var(--aqt-teal)]" title="Verified identity">
                ✓
              </span>
            ) : null}
          </h1>
          {primaryRole ? (
            <div className="aqt-mono flex flex-wrap items-center gap-1.5 text-[12px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex h-4 w-4 items-center justify-center">
                <PlayerRoleIcon role={primaryRole.role} size={14} color={roleSwatchColor} />
              </span>
              <span>{primaryRole.role}</span>
              <span>· {profile.tournaments_count} tournaments</span>
              <span>· {profile.maps_total} maps</span>
            </div>
          ) : null}
          <SocialAccountList accounts={user.social_accounts} className="mt-1 flex flex-wrap gap-1.5" />
        </div>

        <div className="grid w-full items-end gap-4 md:w-auto md:min-w-[460px] md:grid-cols-4">
          <PfStat
            label="Tournaments"
            value={`${profile.tournaments_count}`}
            sub={profile.tournaments_won > 0 ? `${profile.tournaments_won} won` : "—"}
          />
          <PfStat
            label="Winrate"
            value={winrate !== null ? `${winrate.toFixed(2)}` : "-"}
            unit="%"
            delta={winrateDelta !== null ? { value: winrateDelta, good: winrateDelta >= 0 } : undefined}
          />
          <PfStat
            label="Maps"
            value={`${profile.maps_won}`}
            valueSuffix={`/${profile.maps_total}`}
          />
          <PfStat
            label="Avg Place"
            value={formatPlace(profile.avg_placement)}
            sub={profile.avg_playoff_placement !== null ? `Playoffs ${formatPlace(profile.avg_playoff_placement)}` : null}
          />

          <div className="col-span-full mt-2 flex flex-wrap items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
              Form · last {formStreak.length}
            </span>
            {formStreak.length > 0 ? (
              <FormStreak results={formStreak} />
            ) : (
              <span className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">No recent matches</span>
            )}
          </div>
        </div>
      </div>
    </HeroFrame>
  );
};

interface PfStatProps {
  label: string;
  value: string;
  unit?: string;
  valueSuffix?: string;
  sub?: string | null;
  /** Signed change vs the last tournament; `good` controls arrow/colour. */
  delta?: { value: number; good: boolean };
}

const PfStat = ({ label, value, unit, valueSuffix, sub, delta }: PfStatProps) => (
  <div className="flex flex-col gap-1">
    <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</span>
    <span className="font-onest aqt-tnum text-[30px] font-bold leading-none text-[color:var(--aqt-fg)]">
      {value}
      {unit ? <em className="ml-0.5 not-italic text-[color:var(--aqt-teal)]">{unit}</em> : null}
      {valueSuffix ? (
        <span className="text-[22px] text-[color:var(--aqt-fg-faint)]">{valueSuffix}</span>
      ) : null}
    </span>
    {delta ? (
      <span
        className="aqt-mono inline-flex items-center gap-0.5 text-[12px] font-bold"
        style={{ color: delta.good ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
        title="Last tournament vs career"
      >
        {delta.good ? "↑" : "↓"} {Math.abs(delta.value).toFixed(1)}
      </span>
    ) : null}
    {sub ? <span className="text-[12px] text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
  </div>
);

export default UserHeader;
