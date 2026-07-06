"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { Hero, HeroLeaderboardEntry } from "@/types/hero.types";
import { heroVariantFromRole } from "@/components/hero/heroRole";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import { cn } from "@/lib/utils";

import { COL } from "../config/stat-columns";

interface SummaryStat {
  label: string;
  value: React.ReactNode;
  sub: string;
  /** Render the value at the smaller size used for player-name values. */
  small?: boolean;
  /** Render the value in the teal accent (used for Role). */
  accent?: boolean;
}

interface HeroCompareHeroProps {
  selectedHero: Hero | undefined;
  rows: HeroLeaderboardEntry[];
}

const HeroCompareHero = ({ selectedHero, rows }: HeroCompareHeroProps) => {
  const stats = useMemo<SummaryStat[]>(() => {
    const variant = heroVariantFromRole(selectedHero?.type ?? selectedHero?.role);
    const sigKey =
      variant === "support"
        ? "per10_healing"
        : variant === "tank"
          ? "per10_damage_blocked"
          : "per10_damage";
    const sigShort = variant === "support" ? "Healing" : variant === "tank" ? "Blocked" : "Damage";
    const sigDef = COL[sigKey];
    const kdDef = COL.kd;
    const roleLabel = selectedHero?.type ?? selectedHero?.role ?? "—";

    const topSig = rows.length
      ? rows.reduce((best, r) => (sigDef.getValue(r) > sigDef.getValue(best) ? r : best))
      : undefined;
    const bestKd = rows.length ? rows.reduce((best, r) => (r.kd > best.kd ? r : best)) : undefined;

    return [
      {
        label: "Players ranked",
        value: rows.length || "—",
        sub: selectedHero ? `with logged ${selectedHero.name} time` : "pick a hero to rank",
      },
      {
        label: `Top ${sigShort}`,
        value: topSig ? topSig.username : "—",
        sub: topSig ? `${sigDef.formatValue(sigDef.getValue(topSig))} / 10` : "",
        small: true,
      },
      {
        label: "Best K/D",
        value: bestKd ? kdDef.formatValue(bestKd.kd) : "—",
        sub: bestKd ? bestKd.username : "",
      },
      {
        label: "Role",
        value: roleLabel,
        sub: selectedHero ? `${selectedHero.name} · 5 stat columns` : "",
        small: true,
        accent: true,
      },
    ];
  }, [selectedHero, rows]);

  return (
    <PageHero
      eyebrow={
        <HeroCoord className="inline-flex items-center gap-2">
          <Link href="/users" className="transition-colors hover:text-[color:var(--aqt-teal)]">
            Users
          </Link>
          <ChevronRight className="h-3 w-3 opacity-50" />
          <span>Hero compare</span>
        </HeroCoord>
      }
      title={
        <>
          Who plays it <em>best</em>?
        </>
      }
      lede="Pick a hero and rank every player who's logged time on it. Each column ranks the same roster independently — so the elims leader and the healing leader can be different people, side by side."
      aside={
        <div className="grid grid-cols-2 gap-x-7 gap-y-5 text-left sm:grid-cols-4 lg:text-right">
          {stats.map((stat) => (
            <div key={stat.label} className="flex flex-col gap-1 lg:items-end">
              <span className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                {stat.label}
              </span>
              <span
                className={cn(
                  "font-onest font-bold leading-none tabular-nums",
                  stat.small ? "text-2xl" : "text-3xl",
                  stat.accent ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg)]"
                )}
              >
                {stat.value}
              </span>
              {stat.sub ? (
                <span className="text-[10.5px] text-[color:var(--aqt-fg-dim)]">{stat.sub}</span>
              ) : null}
            </div>
          ))}
        </div>
      }
    />
  );
};

export default HeroCompareHero;
