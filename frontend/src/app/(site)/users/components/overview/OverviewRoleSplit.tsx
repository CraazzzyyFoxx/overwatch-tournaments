import React from "react";
import { getTranslations } from "next-intl/server";
import { Layers } from "lucide-react";
import { UserProfile, UserRole } from "@/types/user.types";
import { CardSurface, RolePyramid, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";

// Canonical English role names used ONLY for icon selection in PlayerRoleIcon.
const ROLE_ICON: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

// Reuse the shared role labels (common.roles); damage maps to the dps entry.
const ROLE_LABEL_KEY: Record<AqtRoleKey, string> = {
  tank: "common.roles.tank",
  damage: "common.roles.dps",
  support: "common.roles.support"
};

const ROLE_SHORT_KEY: Record<AqtRoleKey, string> = {
  tank: "users.overview.roleSplit.short.tank",
  damage: "users.overview.roleSplit.short.damage",
  support: "users.overview.roleSplit.short.support"
};

const ROLE_COLOR: Record<AqtRoleKey, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

const formatPercent = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;

interface Bucket {
  key: AqtRoleKey;
  role: UserRole;
  maps: number;
  won: number;
  lost: number;
  winrate: number;
  share: number;
}

interface Props {
  profile: UserProfile;
}

const OverviewRoleSplit = async ({ profile }: Props) => {
  if (!profile.roles.length) return null;

  const t = await getTranslations();
  const totalMaps = profile.maps_total;
  const buckets = ["tank", "damage", "support"]
    .map<Bucket | null>((roleKey) => {
      const role = profile.roles.find((r) => normalizeRole(r.role) === roleKey);
      if (!role) return null;
      return {
        key: roleKey as AqtRoleKey,
        role,
        maps: role.maps,
        won: role.maps_won,
        lost: role.maps - role.maps_won,
        winrate: role.maps > 0 ? role.maps_won / role.maps : 0,
        share: totalMaps > 0 ? role.maps / totalMaps : 0
      };
    })
    .filter((b): b is Bucket => b !== null);

  const primary: Bucket | undefined = buckets.reduce<Bucket | undefined>(
    (best, current) => (best === undefined || current.role.tournaments > best.role.tournaments ? current : best),
    undefined
  );

  return (
    <CardSurface
      title={t("users.overview.roleSplit.title")}
      icon={<Layers size={15} />}
      subtitle={t("users.overview.roleSplit.subtitle", {
        maps: totalMaps,
        tournaments: profile.tournaments_count
      })}
    >
      <div className="flex flex-col gap-3.5">
        <RolePyramid
          segments={buckets.map((b) => ({
            role: b.key,
            maps: b.maps,
            label: b.maps > 0 ? `${t(ROLE_SHORT_KEY[b.key])} ${b.maps}` : ""
          }))}
        />
        <div className="flex flex-col gap-3">
          {buckets.map((b) => (
            <div
              key={b.key}
              className="grid grid-cols-[44px_1fr_auto] items-center gap-3 rounded-[10px] border px-3 py-2.5"
              style={{
                background:
                  b.key === "tank"
                    ? "hsl(210 78% 60% / 0.06)"
                    : b.key === "damage"
                      ? "hsl(340 78% 60% / 0.06)"
                      : "hsl(142 60% 52% / 0.05)",
                borderColor:
                  b.key === "tank"
                    ? "hsl(210 78% 60% / 0.2)"
                    : b.key === "damage"
                      ? "hsl(340 78% 60% / 0.25)"
                      : "hsl(142 60% 52% / 0.2)"
              }}
            >
              <DivisionIcon
                division={b.role.division}
                tournamentGrid={b.role.division_grid_version}
                width={44}
                height={44}
              />
              <div>
                <div
                  className="aqt-display flex items-center gap-1.5 text-[16px] font-bold uppercase leading-none tracking-[0.04em]"
                  style={{ color: ROLE_COLOR[b.key] }}
                >
                  <PlayerRoleIcon role={ROLE_ICON[b.key]} size={14} color={ROLE_COLOR[b.key]} />
                  {t(ROLE_LABEL_KEY[b.key])}
                  {primary && b.key === primary.key ? (
                    <span className="ml-1 text-[11px] font-semibold tracking-[0.1em] text-[color:var(--aqt-fg-muted)]"> · {t("users.overview.roleSplit.main")}</span>
                  ) : null}
                </div>
                <div className="aqt-mono mt-1 text-[12px] text-[color:var(--aqt-fg-muted)]">
                  {b.won}W · {b.lost}L · {t("users.overview.mapsCount", { count: b.maps })}
                </div>
              </div>
              <div className="text-right">
                <div
                  className="aqt-display aqt-tnum text-[22px] font-bold leading-none"
                  style={{
                    color: b.winrate > 0.55
                      ? "var(--aqt-emerald)"
                      : b.winrate < 0.5
                        ? "var(--aqt-rose)"
                        : "var(--aqt-fg)"
                  }}
                >
                  {formatPercent(b.winrate)}
                </div>
                <div className="aqt-mono mt-0.5 text-[11.5px] text-[color:var(--aqt-fg-dim)]">
                  {formatPercent(b.share)} {t("users.overview.roleSplit.ofPool")}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </CardSurface>
  );
};

export default OverviewRoleSplit;
