import { Swords, Trophy, UserCircle, Users, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface KpiCardProps {
  icon: LucideIcon;
  value: number | string;
  label: string;
}

function KpiCard({ icon: Icon, value, label }: KpiCardProps) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card/60 p-4">
      <div className="flex items-center gap-1.5 mb-3">
        <Icon className="size-3.5 text-muted-foreground" />
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      </div>
      <div className="text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

interface KpiStripProps {
  tournaments: { active: number; total: number } | null;
  teams: number | null;
  players: number | null;
  encounters: number | null;
  content: { heroes: number; maps: number; gamemodes: number } | null;
}

export function KpiStrip({ tournaments, teams, players, encounters, content }: KpiStripProps) {
  const items: KpiCardProps[] = [];

  if (tournaments !== null) {
    items.push({
      icon: Trophy,
      value: tournaments.active > 0 ? `${tournaments.active} / ${tournaments.total}` : tournaments.total,
      label: tournaments.active > 0 ? "Active / Total" : "Tournaments",
    });
  }

  if (teams !== null) {
    items.push({ icon: Users, value: teams, label: "Teams" });
  }

  if (players !== null) {
    items.push({ icon: UserCircle, value: players, label: "Players" });
  }

  if (encounters !== null) {
    items.push({ icon: Swords, value: encounters, label: "Encounters" });
  }

  if (content !== null) {
    const parts: string[] = [];
    if (content.heroes > 0) parts.push(`${content.heroes} heroes`);
    if (content.maps > 0) parts.push(`${content.maps} maps`);
    if (content.gamemodes > 0) parts.push(`${content.gamemodes} modes`);
    const total = content.heroes + content.maps + content.gamemodes;
    items.push({
      icon: Trophy,
      value: total,
      label: "Content",
    });
  }

  if (items.length === 0) return null;

  return (
    <div className={cn(
      "grid gap-3",
      items.length >= 5 ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5" :
      items.length >= 3 ? "grid-cols-2 sm:grid-cols-3" :
      "grid-cols-2"
    )}>
      {items.map((item) => (
        <KpiCard key={item.label} {...item} />
      ))}
    </div>
  );
}
