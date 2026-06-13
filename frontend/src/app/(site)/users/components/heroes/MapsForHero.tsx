"use client";

import React from "react";
import { Map as MapIcon } from "lucide-react";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";

export interface HeroMapRow {
  id: number;
  name: string;
  mode: string;
  winRate: number;
  win: number;
  loss: number;
}

const MapsForHero = ({ heroName, heroMaps }: { heroName: string; heroMaps: HeroMapRow[] }) => (
  <CardSurface flush title={`Maps for ${heroName}`} icon={<MapIcon size={15} />}>
    {heroMaps.length > 0 ? (
      heroMaps.map((m, i) => {
        const wr = m.winRate * 100;
        return (
          <div
            key={m.id}
            className="grid grid-cols-[26px_1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 last:border-b-0"
          >
            <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-faint)]">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-[13px] font-medium text-[color:var(--aqt-fg)]">{m.name}</span>
              <span className="aqt-mono text-[10px] uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
                {m.mode}
              </span>
            </div>
            <span
              className="aqt-mono text-right text-[12.5px] font-bold"
              style={{ color: wr >= 55 ? "var(--aqt-emerald)" : wr < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)" }}
            >
              {wr.toFixed(0)}%
            </span>
            <span className="aqt-mono text-right text-[11.5px] text-[color:var(--aqt-fg-muted)]">
              {m.win}-{m.loss}
            </span>
          </div>
        );
      })
    ) : (
      <div className="py-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">
        No map data for this hero yet.
      </div>
    )}
  </CardSurface>
);

export default MapsForHero;
