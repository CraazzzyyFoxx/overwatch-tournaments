"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { UserBestTeammate } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface, heroInitials } from "@/app/(site)/users/components/redesign/atoms";

interface Props {
  teammates: UserBestTeammate[];
  selfName: string;
  totalCount: number;
  totalMaps: number;
}

const TEAMMATE_COLORS = [
  "linear-gradient(135deg, hsl(210 78% 72%), hsl(210 60% 48%))",
  "linear-gradient(135deg, hsl(340 78% 72%), hsl(340 60% 48%))",
  "linear-gradient(135deg, hsl(142 65% 65%), hsl(142 50% 42%))",
  "linear-gradient(135deg, hsl(38 95% 68%), hsl(38 80% 48%))",
  "linear-gradient(135deg, hsl(270 70% 72%), hsl(270 55% 50%))",
  "linear-gradient(135deg, hsl(0 75% 70%), hsl(0 60% 48%))"
];

// Pre-compute layout positions for a synergy network (radial layout)
const POSITIONS = [
  { left: 18, top: 19 },
  { left: 82, top: 23 },
  { left: 12, top: 62 },
  { left: 86, top: 66 },
  { left: 41, top: 90 },
  { left: 58, top: 8 }
];

const playerSlug = (name: string) => name.replace(/#/g, "-");

const formatStat = (value: number | null | undefined, digits: number) =>
  value != null && Number.isFinite(value) ? value.toFixed(digits) : "—";

const OverviewTeammatesSynergy = ({ teammates, selfName, totalCount, totalMaps }: Props) => {
  const [view, setView] = useState<"network" | "all">("network");
  const [search, setSearch] = useState("");

  const top = teammates.slice(0, 6);
  if (top.length === 0) return null;

  const meInitials = heroInitials(selfName.split("#")[0]);

  return (
    <CardSurface
      flush
      title="Best teammates"
      icon={<span>⊕</span>}
      action={
        <button
          type="button"
          className="aqt-seeall"
          onClick={() => setView((v) => (v === "network" ? "all" : "network"))}
        >
          {view === "network" ? "All →" : "← Network"}
        </button>
      }
    >
      {view === "network" ? (
        <NetworkView top={top} meInitials={meInitials} totalCount={totalCount} totalMaps={totalMaps} />
      ) : (
        <AllTeammatesTable teammates={teammates} search={search} onSearchChange={setSearch} />
      )}
    </CardSurface>
  );
};

const NetworkView = ({
  top,
  meInitials,
  totalCount,
  totalMaps
}: {
  top: UserBestTeammate[];
  meInitials: string;
  totalCount: number;
  totalMaps: number;
}) => (
  <>
    <div className="relative h-[280px] p-2">
      <svg viewBox="0 0 320 260" preserveAspectRatio="none" className="absolute inset-0 h-full w-full pointer-events-none">
        <defs>
          <linearGradient id="syn-line" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="hsl(38 95% 55% / 0.5)" />
            <stop offset="1" stopColor="hsl(174 72% 46% / 0.5)" />
          </linearGradient>
        </defs>
        {top.map((tm, i) => {
          const pos = POSITIONS[i] ?? POSITIONS[POSITIONS.length - 1];
          const x = (pos.left / 100) * 320;
          const y = (pos.top / 100) * 260;
          const width = Math.max(1.5, Math.min(3, 1 + tm.tournaments * 0.7));
          return <line key={tm.user.id} x1={160} y1={130} x2={x} y2={y} stroke="url(#syn-line)" strokeWidth={width} />;
        })}
      </svg>
      <SynNode left={50} top={50} initials={meInitials} name="You" isMe accent="var(--aqt-amber)" />
      {top.map((tm, i) => {
        const pos = POSITIONS[i] ?? POSITIONS[POSITIONS.length - 1];
        const [tmName, tmTag] = tm.user.name.split("#");
        return (
          <SynNode
            key={tm.user.id}
            left={pos.left}
            top={pos.top}
            initials={heroInitials(tmName)}
            name={tmName}
            tag={tmTag ? `#${tmTag}` : ""}
            sub={`×${tm.tournaments} · ${(tm.winrate * 100).toFixed(0)}% WR`}
            avBg={TEAMMATE_COLORS[i % TEAMMATE_COLORS.length]}
          />
        );
      })}
    </div>
    <div className="aqt-mono flex justify-between border-t border-[color:var(--aqt-border)] px-[18px] py-2.5 text-[11px] text-[color:var(--aqt-fg-dim)]">
      <span>Edges sized by appearances</span>
      <span>
        {totalCount} unique · {totalMaps} maps
      </span>
    </div>
  </>
);

const AllTeammatesTable = ({
  teammates,
  search,
  onSearchChange
}: {
  teammates: UserBestTeammate[];
  search: string;
  onSearchChange: (value: string) => void;
}) => {
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = [...teammates].sort((a, b) => b.tournaments - a.tournaments);
    if (!q) return rows;
    return rows.filter((t) => t.user.name.toLowerCase().includes(q));
  }, [teammates, search]);

  return (
    <div className="flex flex-col">
      <div className="border-b border-[color:var(--aqt-border)] px-3.5 py-2.5">
        <div className="relative">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search teammates…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[12.5px] text-[color:var(--aqt-fg)] outline-none"
          />
        </div>
      </div>
      <div className="max-h-[300px] overflow-y-auto">
        <table className="aqt-tnum w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              {["Player", "×played", "WR", "KDA", "MVP"].map((h, i) => (
                <th
                  key={h}
                  className={cnHeader(i === 0)}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((tm) => {
              const [tmName, tmTag] = tm.user.name.split("#");
              return (
                <tr key={tm.user.id} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                  <td className="px-3.5 py-2">
                    <Link href={`/users/${playerSlug(tm.user.name)}`} className="inline-flex items-center gap-1.5 hover:text-[color:var(--aqt-teal)]">
                      <span className="font-semibold text-[color:var(--aqt-fg)]">{tmName}</span>
                      {tmTag ? <span className="aqt-mono text-[10px] text-[color:var(--aqt-fg-faint)]">#{tmTag}</span> : null}
                    </Link>
                  </td>
                  <td className="aqt-mono px-3.5 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.tournaments}</td>
                  <td
                    className="aqt-mono px-3.5 py-2 text-right font-semibold"
                    style={{
                      color: tm.winrate >= 0.55 ? "var(--aqt-emerald)" : tm.winrate < 0.45 ? "var(--aqt-rose)" : "var(--aqt-amber)"
                    }}
                  >
                    {(tm.winrate * 100).toFixed(0)}%
                  </td>
                  <td className="aqt-mono px-3.5 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.KDA], 2)}
                  </td>
                  <td className="aqt-mono px-3.5 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.Performance], 1)}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3.5 py-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">
                  No teammates match search
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const cnHeader = (left: boolean) =>
  `aqt-mono border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-3.5 py-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)] ${
    left ? "text-left" : "text-right"
  }`;

interface SynNodeProps {
  left: number;
  top: number;
  initials: string;
  name: string;
  tag?: string;
  sub?: string;
  isMe?: boolean;
  accent?: string;
  avBg?: string;
}

const SynNode = ({ left, top, initials, name, tag, sub, isMe, accent, avBg }: SynNodeProps) => (
  <div
    className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 text-center"
    style={{ left: `${left}%`, top: `${top}%` }}
  >
    <div
      className="flex items-center justify-center rounded-full border border-[color:var(--aqt-border-2)] aqt-display font-extrabold text-[color:var(--aqt-fg-muted)]"
      style={{
        width: isMe ? 56 : 44,
        height: isMe ? 56 : 44,
        fontSize: isMe ? 16 : 13,
        background: isMe ? "linear-gradient(135deg,#a87d4f,#5a3b22)" : (avBg ?? "linear-gradient(135deg,#3a5168,#1c2937)"),
        color: isMe ? "hsl(30 30% 12%)" : "hsl(220 30% 8%)",
        boxShadow: isMe ? "0 0 0 3px hsl(38 95% 55% / 0.25)" : "none"
      }}
    >
      {initials}
    </div>
    <div className="whitespace-nowrap text-[11px] font-semibold" style={{ color: accent ?? "var(--aqt-fg)" }}>
      {name}
      {tag ? <span className="text-[color:var(--aqt-fg-faint)]"> {tag}</span> : null}
    </div>
    {sub ? <div className="aqt-mono text-[10px] text-[color:var(--aqt-fg-dim)]">{sub}</div> : null}
  </div>
);

export default OverviewTeammatesSynergy;
