"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { Hero, HeroLeaderboardEntry } from "@/types/hero.types";
import { heroVariantFromRole } from "@/components/hero/heroRole";

import { COL } from "../config/stat-columns";

// Hexagon lattice + dual radial glows — the only raw CSS the redesign needs
// (not expressible as utilities). Mirrors `.hero/.hex/.glow-1/.glow-2` from the
// imported mockup.
const HEX_BG =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='92.4'%3E%3Cpolygon points='40,1 79,23.2 79,69.2 40,91.4 1,69.2 1,23.2' fill='none' stroke='white' stroke-width='0.8' opacity='0.055'/%3E%3C/svg%3E\")";
const GLOW_1 = "radial-gradient(ellipse at 30% 50%, hsl(174 72% 46% / 0.16), transparent 62%)";
const GLOW_2 = "radial-gradient(ellipse at 70% 30%, hsl(340 75% 58% / 0.12), transparent 58%)";

const DISPLAY = "font-[family-name:var(--aqt-display)]";

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
    <section className="relative overflow-hidden rounded-[var(--aqt-radius)] border border-[var(--aqt-border)] bg-[var(--aqt-bg)] px-6 py-8 md:px-10 md:py-[34px]">
      <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: HEX_BG, backgroundSize: "80px 92.4px" }} />
      <div className="pointer-events-none absolute -left-[5%] -top-[15%] h-[130%] w-[65%]" style={{ background: GLOW_1 }} />
      <div className="pointer-events-none absolute -top-[25%] right-0 h-full w-[55%]" style={{ background: GLOW_2 }} />

      <div className="relative grid items-end gap-7 lg:grid-cols-[1fr_auto] lg:gap-12">
        <div>
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--aqt-fg-faint)]">
            <Link href="/users" className="transition-colors hover:text-[var(--aqt-teal)]">
              Users
            </Link>
            <ChevronRight className="h-3 w-3 opacity-50" />
            <span>Hero compare</span>
          </p>
          <h1 className={`${DISPLAY} my-3 text-4xl font-bold uppercase leading-[1.05] tracking-[0.02em] md:text-5xl`}>
            Who plays it <span className="text-[var(--aqt-teal)]">best</span>?
          </h1>
          <p className="max-w-[44rem] text-sm text-[var(--aqt-fg-muted)]">
            Pick a hero and rank every player who&apos;s logged time on it. Each column ranks the same roster
            independently — so the elims leader and the healing leader can be different people, side by side.
          </p>
        </div>

        <div className="grid min-w-0 grid-cols-2 gap-x-7 gap-y-5 text-left sm:grid-cols-4 lg:text-right">
          {stats.map((stat) => (
            <div key={stat.label} className="flex flex-col gap-1 lg:items-end">
              <span className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-[var(--aqt-fg-faint)]">
                {stat.label}
              </span>
              <span
                className={`${DISPLAY} font-bold leading-none tabular-nums ${stat.small ? "text-2xl" : "text-3xl"} ${
                  stat.accent ? "text-[var(--aqt-teal)]" : "text-[var(--aqt-fg)]"
                }`}
              >
                {stat.value}
              </span>
              {stat.sub ? <span className="text-[10.5px] text-[var(--aqt-fg-dim)]">{stat.sub}</span> : null}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default HeroCompareHero;
