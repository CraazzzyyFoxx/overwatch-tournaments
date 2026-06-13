import React from "react";
import Image from "next/image";
import Link from "next/link";
import { User, UserProfile } from "@/types/user.types";
import { getPlayerImage } from "@/utils/player";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { FormStreak, type FormResult } from "@/app/(site)/users/components/redesign/atoms";
import ProfileToolbar from "@/app/(site)/users/components/redesign/ProfileToolbar";
import userService from "@/services/user.service";

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
  const formStreak = await deriveFormStreak(user.id);
  const roleSwatchColor =
    primaryRole?.role === "Tank"
      ? "var(--aqt-tank)"
      : primaryRole?.role === "Support"
        ? "var(--aqt-support)"
        : "var(--aqt-damage)";

  return (
    <section className="aqt-player relative overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='92.4'%3E%3Cpolygon points='40,1 79,23.2 79,69.2 40,91.4 1,69.2 1,23.2' fill='none' stroke='white' stroke-width='0.8' opacity='0.055'/%3E%3C/svg%3E\")",
          backgroundSize: "80px 92.4px"
        }}
      />
      <div
        className="pointer-events-none absolute -left-[5%] -top-[20%] h-[140%] w-[60%]"
        style={{ background: "radial-gradient(ellipse at 30% 50%, hsl(340 78% 60% / 0.15), transparent 62%)" }}
      />
      <div
        className="pointer-events-none absolute -right-[5%] -top-[25%] h-[120%] w-[55%]"
        style={{ background: "radial-gradient(ellipse at 70% 40%, hsl(174 72% 46% / 0.12), transparent 58%)" }}
      />

      <div className="relative z-[1] flex items-center justify-between gap-3 px-9 pt-5">
        <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          <Link href="/users" className="hover:text-[color:var(--aqt-fg-muted)]">Users</Link>
          <span className="mx-1">·</span>
          <span className="text-[color:var(--aqt-fg-muted)]">{name}</span>
        </p>
        <ProfileToolbar />
      </div>

      <div className="relative z-[1] grid items-center gap-8 p-7 pt-6 md:grid-cols-[auto_1fr_auto] md:px-9 md:py-7">
        <div className="relative h-[110px] w-[110px] flex-shrink-0">
          <div
            className="absolute -inset-1 rounded-[22px] opacity-60 blur-2xl"
            style={{
              background:
                "linear-gradient(135deg,var(--aqt-damage),var(--aqt-amber),var(--aqt-teal))"
            }}
          />
          <div className="relative h-full w-full overflow-hidden rounded-[18px] border border-[color:hsl(30_40%_22%)]">
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
          <h1 className="m-0 flex flex-wrap items-baseline gap-2.5 text-[clamp(28px,4vw,48px)] aqt-display font-bold uppercase tracking-[0.02em] leading-none">
            <span>{name}</span>
            {tag ? <span className="text-[22px] font-medium tracking-[0.04em] text-[color:var(--aqt-fg-faint)]">#{tag}</span> : null}
            {user.battle_tag.length > 0 ? (
              <span className="text-[18px] text-[color:var(--aqt-teal)]" title="Verified roster">
                ✓
              </span>
            ) : null}
          </h1>
          {primaryRole ? (
            <div className="aqt-mono flex flex-wrap items-center gap-1.5 text-[11px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex h-4 w-4 items-center justify-center">
                <PlayerRoleIcon role={primaryRole.role} size={14} color={roleSwatchColor} />
              </span>
              <span>{primaryRole.role}</span>
              <span>· Div {primaryRole.division}</span>
              <span>· {profile.tournaments_count} tournaments</span>
              <span>· {profile.maps_total} maps</span>
            </div>
          ) : null}
          <div className="mt-1 flex flex-wrap gap-1.5">
            {user.battle_tag.map((bt) => (
              <span
                key={bt.id}
                className="inline-flex items-center gap-1.5 rounded-[7px] border px-2 py-1 text-[11.5px] font-medium"
                style={{
                  background: "hsl(210 80% 60% / 0.06)",
                  borderColor: "hsl(210 80% 60% / 0.25)",
                  color: "var(--aqt-blue)"
                }}
              >
                <Image src="/battlenet.svg" width={12} height={12} alt="Battle.net" />
                {bt.battle_tag}
              </span>
            ))}
            {user.twitch.map((tw) => (
              <span
                key={tw.id}
                className="inline-flex items-center gap-1.5 rounded-[7px] border px-2 py-1 text-[11.5px] font-medium"
                style={{
                  background: "hsl(270 70% 62% / 0.06)",
                  borderColor: "hsl(270 70% 62% / 0.25)",
                  color: "var(--aqt-violet)"
                }}
              >
                <Image src="/twitch.png" width={12} height={12} alt="Twitch" />
                {tw.name}
              </span>
            ))}
            {user.discord.map((dc) => (
              <span
                key={dc.id}
                className="inline-flex items-center gap-1.5 rounded-[7px] border px-2 py-1 text-[11.5px] font-medium"
                style={{
                  background: "hsl(220 70% 60% / 0.06)",
                  borderColor: "hsl(220 70% 60% / 0.25)",
                  color: "hsl(220 70% 70%)"
                }}
              >
                <Image src="/discord.png" width={12} height={12} alt="Discord" />
                {dc.name}
              </span>
            ))}
          </div>
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
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
              Form · last {formStreak.length}
            </span>
            {formStreak.length > 0 ? (
              <FormStreak results={formStreak} />
            ) : (
              <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">No recent matches</span>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};

interface PfStatProps {
  label: string;
  value: string;
  unit?: string;
  valueSuffix?: string;
  sub?: string | null;
}

const PfStat = ({ label, value, unit, valueSuffix, sub }: PfStatProps) => (
  <div className="flex flex-col gap-1">
    <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</span>
    <span className="aqt-display aqt-tnum text-[30px] font-bold leading-none text-[color:var(--aqt-fg)]">
      {value}
      {unit ? <em className="ml-0.5 not-italic text-[color:var(--aqt-teal)]">{unit}</em> : null}
      {valueSuffix ? (
        <span className="text-[22px] text-[color:var(--aqt-fg-faint)]">{valueSuffix}</span>
      ) : null}
    </span>
    {sub ? <span className="text-[11px] text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
  </div>
);

export default UserHeader;
