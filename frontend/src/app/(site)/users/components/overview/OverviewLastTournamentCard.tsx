"use client";

import React from "react";
import { Trophy } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { UserTournamentWithStats, UserTournamentSummary } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

interface Props {
  tournament: UserTournamentWithStats;
  tournaments: UserTournamentSummary[];
}

const compactNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return value.toFixed(2);
};

const formatPercent = (value: number | null | undefined, digits = 0) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
};

const roleColor = (role: string) => {
  if (role === "Tank") return "var(--aqt-tank)";
  if (role === "Support") return "var(--aqt-support)";
  return "var(--aqt-damage)";
};

const StatBlock = ({
  label,
  value,
  rank,
  total,
  highlight
}: {
  label: string;
  value: string;
  rank?: number;
  total?: number;
  highlight?: "good" | "bad";
}) => (
  <div>
    <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">{label}</div>
    <div
      className="aqt-display aqt-tnum text-[22px] font-bold leading-[1.1]"
      style={{ color: highlight === "good" ? "var(--aqt-emerald)" : highlight === "bad" ? "var(--aqt-rose)" : "var(--aqt-fg)" }}
    >
      {value}
    </div>
    {rank !== undefined && total !== undefined ? (
      <div className="aqt-mono text-[11.5px] text-[color:var(--aqt-fg-dim)]">
        #{rank} / {total}
      </div>
    ) : null}
  </div>
);

const OverviewLastTournamentCard = ({ tournament, tournaments }: Props) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const playtimeH = Math.floor(tournament.playtime / 3600);
  const playtimeM = Math.floor((tournament.playtime % 3600) / 60);
  const mapsLost = tournament.maps - tournament.maps_won;
  const winrate = tournament.maps > 0 ? tournament.maps_won / tournament.maps : null;

  const onSelectTournament = (value: string) => {
    const nextSearchParams = new URLSearchParams(searchParams || undefined);
    nextSearchParams.set("tournamentId", value);
    router.push(`${pathname}?${nextSearchParams.toString()}`);
  };

  return (
    <CardSurface
      title={
        <Link href={`/tournaments/${tournament.id}`} className="hover:text-[color:var(--aqt-teal)]">
          {tournament.name}
        </Link>
      }
      icon={<Trophy size={15} />}
      action={
        tournaments.length > 0 ? (
          <Select value={String(tournament.id)} onValueChange={onSelectTournament}>
            <SelectTrigger className="h-7 w-44 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[12.5px]">
              <SelectValue placeholder="Select tournament" />
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel max-h-[min(var(--radix-select-content-available-height),20rem)]">
              <SelectGroup>
                {tournaments.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)} className="text-[13px]">
                    {t.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        ) : null
      }
    >
      <div className="flex flex-col gap-3.5">
        <div className="flex items-center gap-3.5">
          <DivisionIcon
            division={tournament.division}
            tournamentGrid={tournament.division_grid_version}
            width={52}
            height={52}
          />
          <div className="flex-1 min-w-0">
            <div
              className="aqt-display flex items-center gap-1.5 text-[20px] font-bold uppercase leading-none"
              style={{ color: roleColor(tournament.role) }}
            >
              <PlayerRoleIcon role={tournament.role} size={18} color={roleColor(tournament.role)} />
              {tournament.role}
            </div>
            <div className="aqt-mono mt-1 text-[13px] text-[color:var(--aqt-fg-muted)]">
              Placed <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">
                {tournament.group_placement ?? tournament.playoff_placement ?? "—"}
              </span>
              {" · "}
              {playtimeH > 0 ? `${playtimeH}h ` : ""}{playtimeM}m playtime · {tournament.maps} maps
            </div>
          </div>
          <div className="text-right">
            <div className="aqt-display text-[28px] font-bold leading-none">
              <span style={{ color: "var(--aqt-emerald)" }}>{tournament.maps_won}</span>
              <span className="text-[18px] text-[color:var(--aqt-fg-faint)]"> W</span>
              <span className="mx-1.5">·</span>
              <span style={{ color: "var(--aqt-rose)" }}>{mapsLost}</span>
              <span className="text-[18px] text-[color:var(--aqt-fg-faint)]"> L</span>
            </div>
            <div className="aqt-mono mt-1 text-[12px] text-[color:var(--aqt-fg-dim)]">{formatPercent(winrate)} map winrate</div>
          </div>
        </div>
        {tournament.stats ? (
          <div className="grid grid-cols-2 gap-2.5 border-t border-[color:var(--aqt-border)] pt-3 sm:grid-cols-4">
            {tournament.stats.kda ? (
              <StatBlock
                label="KDA"
                value={compactNumber(tournament.stats.kda.value)}
                rank={tournament.stats.kda.rank}
                total={tournament.stats.kda.total}
              />
            ) : null}
            {tournament.stats.performance ? (
              <StatBlock
                label="MVP score"
                value={compactNumber(tournament.stats.performance.value)}
                rank={tournament.stats.performance.rank}
                total={tournament.stats.performance.total}
              />
            ) : null}
            {tournament.stats.hero_damage_dealt ? (
              <StatBlock
                label="Dmg/map"
                value={compactNumber(tournament.stats.hero_damage_dealt.value)}
                rank={tournament.stats.hero_damage_dealt.rank}
                total={tournament.stats.hero_damage_dealt.total}
              />
            ) : null}
            {tournament.stats.damage_delta ? (
              <StatBlock
                label="Δ Damage"
                value={tournament.stats.damage_delta.value >= 0 ? `+${compactNumber(tournament.stats.damage_delta.value)}` : compactNumber(tournament.stats.damage_delta.value)}
                rank={tournament.stats.damage_delta.rank}
                total={tournament.stats.damage_delta.total}
                highlight={tournament.stats.damage_delta.value >= 0 ? "good" : "bad"}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default OverviewLastTournamentCard;
