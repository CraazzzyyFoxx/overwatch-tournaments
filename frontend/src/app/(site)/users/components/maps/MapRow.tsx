"use client";

import Image from "@/components/ui/image";
import { UserMapRead } from "@/types/user.types";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import CharacterCard, { CharacterMapStats } from "@/components/profile/CharacterCard";
import ProfileWidget from "@/components/profile/ProfileWidget";
import { AvatarStack } from "@/components/ui/avatar";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Progress } from "@/components/ui/progress";
import { winrateColor, winrateTone } from "@/lib/colors";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";

const MapRow = ({ row, discipline, axis }: { row: UserMapRead; discipline: string; axis: WorkspaceAxis }) => {
  const wr = row.win_rate * 100;
  const wrColor = winrateColor(wr);
  const characterStats = row.character_stats ?? [];
  return (
    <div
      key={row.map.id}
      className="grid grid-cols-[64px_1fr_1fr_minmax(0,1.2fr)_60px_50px] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-4.5 py-2.75 transition-colors last:border-b-0 hover:bg-[color:var(--aqt-overlay-2)]"
    >
      <div className="relative flex h-8 w-14 items-center justify-center overflow-hidden rounded-md border border-[color:var(--aqt-border-2)] bg-linear-135 from-[color:var(--aqt-card-2)] to-[color:var(--aqt-bg-2)] font-display text-label font-extrabold text-[color:var(--aqt-fg-muted)]">
        {row.map.image_path ? (
          <Image src={row.map.image_path} alt={row.map.name} fill sizes="56px" className="object-cover" />
        ) : (
          <span>{row.map.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}</span>
        )}
      </div>
      <div className="flex flex-col leading-tight">
        <div className="text-body font-semibold text-[color:var(--aqt-fg)]">{row.map.name}</div>
        <Eyebrow as="div" tone="dim" className="aqt-tnum">
          {row.map.parent?.name ?? "—"}
        </Eyebrow>
      </div>
      <div className="flex items-center gap-2.5">
        {/* The number beside it is what a reader hears; the bar is its picture. */}
        <Progress
          value={wr}
          size="sm"
          tone={winrateTone(wr)}
          aria-hidden
          className="flex-1"
        />
        <span className="aqt-tnum min-w-9 text-right text-label font-semibold" style={{ color: wrColor }}>
          {wr.toFixed(0)}%
        </span>
      </div>
      {characterStats.length > 0 ? (
        <AvatarStack max={8} size={26}>
          {characterStats.map((hs) => (
            <CatalogEntityImage
              key={`${row.map.id}:${hs.character.id}`}
              entity={hs.character}
              size="sm"
              popover={
                <ProfileWidget
                  axis={axis}
                  discipline={discipline}
                  slot="characterPopover"
                  props={{ entity: hs.character, mapStats: hs, mapCharacters: characterStats, mapWinRate: row.win_rate }}
                  fallback={
                    <CharacterCard entity={hs.character}>
                      <CharacterMapStats stats={hs} characters={characterStats} mapWinRate={row.win_rate} />
                    </CharacterCard>
                  }
                />
              }
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
