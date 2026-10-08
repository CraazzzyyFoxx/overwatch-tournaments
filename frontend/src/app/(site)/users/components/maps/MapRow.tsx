"use client";

import Image from "next/image";
import { UserMapRead } from "@/types/user.types";
import HeroImage from "@/components/hero/HeroImage";
import HeroUserStatsPopover from "@/components/hero/HeroUserStatsPopover";
import { AvatarStack } from "@/components/ui/avatar";
import { winrateColor } from "@/app/(site)/users/components/heroes/utils";

const MapRow = ({ row }: { row: UserMapRead }) => {
  const wr = row.win_rate * 100;
  const wrColor = winrateColor(wr);
  const heroStats = row.hero_stats ?? [];
  return (
    <div key={row.map.id} className="aqt-map-row" style={{ gridTemplateColumns: "64px 1fr 1fr minmax(0,1.2fr) 60px 50px" }}>
      <div className="aqt-map-thumb">
        {row.map.image_path ? (
          <Image src={row.map.image_path} alt={row.map.name} fill sizes="56px" className="object-cover" />
        ) : (
          <span>{row.map.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}</span>
        )}
      </div>
      <div className="flex flex-col leading-tight">
        <div className="text-body font-semibold text-[color:var(--aqt-fg)]">{row.map.name}</div>
        <div className="aqt-tnum text-label uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
          {row.map.gamemode?.name ?? "—"}
        </div>
      </div>
      <div className="aqt-wr-bar">
        <div className="aqt-track">
          <div className="aqt-fill" style={{ width: `${wr}%`, background: wrColor }} />
        </div>
        <span className="aqt-num tabular-nums" style={{ color: wrColor }}>
          {wr.toFixed(0)}%
        </span>
      </div>
      {heroStats.length > 0 ? (
        <AvatarStack max={8} size={26}>
          {heroStats.map((hs) => (
            <HeroImage
              key={`${row.map.id}:${hs.hero.id}`}
              hero={hs.hero}
              size="sm"
              popover={<HeroUserStatsPopover hero={hs.hero} mapStats={hs} />}
            />
          ))}
        </AvatarStack>
      ) : (
        <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">—</span>
      )}
      <span className="aqt-tnum text-right text-caption font-semibold text-[color:var(--aqt-fg-muted)]">
        {row.win}-{row.loss}-{row.draw}
      </span>
      <span className="aqt-tnum text-right text-body font-semibold">{row.count}</span>
    </div>
  );
};

export default MapRow;
