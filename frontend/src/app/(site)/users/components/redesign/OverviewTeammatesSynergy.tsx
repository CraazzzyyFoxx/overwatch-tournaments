import React from "react";
import { UserBestTeammate } from "@/types/user.types";
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

const OverviewTeammatesSynergy = ({ teammates, selfName, totalCount, totalMaps }: Props) => {
  const top = teammates.slice(0, 6);
  if (top.length === 0) return null;

  const meInitials = heroInitials(selfName.split("#")[0]);

  return (
    <CardSurface
      flush
      title="Best teammates"
      icon={<span>⊕</span>}
      action={<span className="aqt-seeall">{totalCount} stack-mates</span>}
    >
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
            return (
              <line
                key={tm.user.id}
                x1={160}
                y1={130}
                x2={x}
                y2={y}
                stroke="url(#syn-line)"
                strokeWidth={width}
              />
            );
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
      <div
        className="aqt-mono flex justify-between border-t border-[color:var(--aqt-border)] px-[18px] py-2.5 text-[11px] text-[color:var(--aqt-fg-dim)]"
      >
        <span>Edges sized by appearances</span>
        <span>{totalCount} unique · {totalMaps} maps</span>
      </div>
    </CardSurface>
  );
};

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
