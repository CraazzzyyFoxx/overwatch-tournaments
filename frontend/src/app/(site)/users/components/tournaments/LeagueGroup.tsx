"use client";

import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";
import TournamentItem from "@/app/(site)/users/components/tournaments/TournamentItem";

// ─── League group (collapsible parent over division entries) ────────────────────

const LeagueGroup = ({
  name,
  entries,
  selfUserId,
  isOpen,
  onToggle,
  isTournamentOpen,
  onToggleTournament
}: {
  name: string;
  entries: UserTournament[];
  selfUserId: number;
  isOpen: boolean;
  onToggle: () => void;
  isTournamentOpen: (t: UserTournament) => boolean;
  onToggleTournament: (t: UserTournament) => void;
}) => {
  const bestPlacement = entries.reduce((best, t) => (t.placement && t.placement < best ? t.placement : best), Infinity);

  return (
    <div className="border-b border-[color:var(--aqt-border)]">
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-[hsl(0_0%_100%/0.02)]"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <span
          className="aqt-mono rounded-[5px] border px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em]"
          style={{
            background: "hsl(258 60% 62% / 0.1)",
            borderColor: "hsl(258 60% 62% / 0.25)",
            color: "var(--aqt-violet)"
          }}
        >
          League
        </span>
        <span className="flex-1 truncate text-[17px] font-semibold text-[color:var(--aqt-fg)]">{name}</span>
        <span className="aqt-mono text-[12.5px] text-[color:var(--aqt-fg-dim)]">
          {entries.length} divisions
          {bestPlacement !== Infinity ? ` · best #${bestPlacement}` : ""}
        </span>
        <div
          className={cn("transition-transform", isOpen && "rotate-180")}
          style={{ color: isOpen ? "var(--aqt-teal)" : "var(--aqt-fg-faint)" }}
        >
          ▾
        </div>
      </div>

      {isOpen ? (
        <div className="border-t border-[color:var(--aqt-border)] pl-4">
          {entries.map((t) => (
            <TournamentItem
              key={t.id}
              t={t}
              selfUserId={selfUserId}
              isOpen={isTournamentOpen(t)}
              onToggle={() => onToggleTournament(t)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
};

export default LeagueGroup;
