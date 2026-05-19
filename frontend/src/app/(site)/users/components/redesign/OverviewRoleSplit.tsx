import React from "react";
import { UserProfile, UserRole } from "@/types/user.types";
import { CardSurface, RolePyramid, normalizeRole, type AqtRoleKey } from "@/app/(site)/users/components/redesign/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";

const ROLE_LABELS: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

const ROLE_SHORT: Record<AqtRoleKey, string> = {
  tank: "T",
  damage: "Damage",
  support: "Sup"
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

const OverviewRoleSplit = ({ profile }: Props) => {
  if (!profile.roles.length) return null;

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
      title="Role split"
      icon={<span>▣</span>}
      subtitle={`${totalMaps} maps · ${profile.tournaments_count} tournaments`}
    >
      <div className="flex flex-col gap-3.5">
        <RolePyramid
          segments={buckets.map((b) => ({
            role: b.key,
            maps: b.maps,
            label: b.maps > 0 ? `${ROLE_SHORT[b.key]} ${b.maps}` : ""
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
                  className="aqt-display flex items-center gap-1.5 text-[15px] font-bold uppercase leading-none tracking-[0.04em]"
                  style={{ color: ROLE_COLOR[b.key] }}
                >
                  <PlayerRoleIcon role={ROLE_LABELS[b.key]} size={14} color={ROLE_COLOR[b.key]} />
                  {ROLE_LABELS[b.key]}
                  {primary && b.key === primary.key ? (
                    <span className="ml-1 text-[10px] font-semibold tracking-[0.1em] text-[color:var(--aqt-fg-muted)]"> · Main</span>
                  ) : null}
                </div>
                <div className="aqt-mono mt-1 text-[11px] text-[color:var(--aqt-fg-muted)]">
                  {b.won}W · {b.lost}L · {b.maps} maps
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
                <div className="aqt-mono mt-0.5 text-[10.5px] text-[color:var(--aqt-fg-dim)]">
                  {formatPercent(b.share)} of pool
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
