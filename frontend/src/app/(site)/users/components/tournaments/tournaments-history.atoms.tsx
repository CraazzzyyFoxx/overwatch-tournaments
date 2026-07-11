import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { placementMedal, type PlacementMedal } from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";

// ─── Master-detail (Event dossier) atoms ────────────────────────────────────────

const MEDAL_STYLE: Record<PlacementMedal, React.CSSProperties> = {
  gold: { background: "hsl(42 63% 60% / 0.14)", border: "1px solid hsl(42 63% 60% / 0.4)", color: "var(--aqt-gold)" },
  silver: { background: "hsl(212 21% 73% / 0.12)", border: "1px solid hsl(212 21% 73% / 0.35)", color: "var(--aqt-silver)" },
  bronze: { background: "hsl(26 49% 54% / 0.12)", border: "1px solid hsl(26 49% 54% / 0.35)", color: "var(--aqt-bronze)" },
  none: { background: "hsl(0 0% 100% / 0.03)", border: "1px solid var(--aqt-border-2)", color: "var(--aqt-fg-muted)" }
};

/** Square placement badge with medal colours (gold/silver/bronze) for the top 3. */
export const PlaceBadge = ({ placement, size = "md" }: { placement: number | null; size?: "sm" | "md" | "lg" }) => {
  const px = size === "lg" ? 44 : size === "sm" ? 28 : 36;
  const font = size === "lg" ? 20 : size === "sm" ? 13 : 16;
  return (
    <span
      className="aqt-display aqt-tnum inline-flex shrink-0 items-center justify-center rounded-[7px] font-bold leading-none"
      style={{ ...MEDAL_STYLE[placementMedal(placement)], width: px, height: px, fontSize: font }}
    >
      {placement && placement > 0 ? placement : "—"}
    </span>
  );
};

/** Violet "League" pill (matches the former LeagueGroup badge). */
export const LeagueBadge = ({ children }: { children: React.ReactNode }) => (
  <span
    className="aqt-mono shrink-0 rounded-[5px] border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em]"
    style={{ background: "hsl(258 60% 62% / 0.1)", borderColor: "hsl(258 60% 62% / 0.25)", color: "var(--aqt-violet)" }}
  >
    {children}
  </span>
);

/** W-D-L record as coloured mono text. Draws are hidden when zero. */
export const WdlText = ({
  won,
  lost,
  draw,
  className
}: {
  won: number;
  lost: number;
  draw: number;
  className?: string;
}) => {
  const t = useTranslations();
  return (
    <span className={cn("aqt-mono aqt-tnum", className)}>
      <span style={{ color: "var(--aqt-emerald)" }}>{t("users.tournaments.stat.wins", { count: String(won) })}</span>{" "}
      <span style={{ color: "var(--aqt-rose)" }}>{t("users.tournaments.stat.losses", { count: String(lost) })}</span>
      {draw > 0 ? (
        <>
          {" "}
          <span style={{ color: "var(--aqt-amber)" }}>{t("users.tournaments.stat.draws", { count: String(draw) })}</span>
        </>
      ) : null}
    </span>
  );
};

/** Thin stacked W-D-L bar (win / draw / loss segments). */
export const WdlBar = ({
  won,
  lost,
  draw,
  className
}: {
  won: number;
  lost: number;
  draw: number;
  className?: string;
}) => {
  const total = won + lost + draw;
  return (
    <span className={cn("inline-flex h-[5px] w-16 overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]", className)}>
      {total > 0 ? (
        <>
          <span style={{ width: `${(won / total) * 100}%`, background: "var(--aqt-emerald)" }} />
          <span style={{ width: `${(draw / total) * 100}%`, background: "var(--aqt-amber)" }} />
          <span style={{ width: `${(lost / total) * 100}%`, background: "var(--aqt-rose)" }} />
        </>
      ) : null}
    </span>
  );
};

export interface SummaryCell {
  key: string;
  label: string;
  value: React.ReactNode;
  color?: string;
}

/** Open hairline summary strip — top+bottom border only, cells hairline-divided.
 *  Scrolls horizontally inside its own container on narrow screens (§7). */
export const SummaryStrip = ({ cells }: { cells: SummaryCell[] }) => (
  <div className="overflow-x-auto border-y border-[color:var(--aqt-border)]">
    <div className="grid min-w-[540px] grid-cols-6">
      {cells.map((cell) => (
        <div
          key={cell.key}
          className="flex flex-col gap-1 border-l border-[color:var(--aqt-border)] px-3 py-2.5 first:border-l-0"
        >
          <span className="aqt-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
            {cell.label}
          </span>
          <span className="aqt-display aqt-tnum text-[16px] font-bold leading-none" style={{ color: cell.color ?? "var(--aqt-fg)" }}>
            {cell.value}
          </span>
        </div>
      ))}
    </div>
  </div>
);
