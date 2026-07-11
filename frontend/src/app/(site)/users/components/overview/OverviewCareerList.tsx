import React from "react";
import { getTranslations } from "next-intl/server";
import { Medal } from "lucide-react";
import { UserProfile, UserTournament } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";

interface Props {
  profile: UserProfile;
  /** Full tournament list (already fetched by the page) — the only source with
   *  per-event `placement` + `count_teams`, which drives the finishes bar. */
  tournaments?: UserTournament[];
}

const fmt = (value: number | null | undefined, digits = 2, suffix = "") => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
};

const Row = ({
  label,
  value,
  highlight,
  title
}: {
  label: string;
  value: string;
  highlight?: string;
  title?: string;
}) => (
  <div className="flex items-center justify-between border-b border-[color:var(--aqt-border)] px-[18px] py-[9px] last:border-b-0">
    <span className="text-[12.5px] text-[color:var(--aqt-fg-muted)]" title={title}>
      {label}
    </span>
    <span className="aqt-tnum text-[13px] font-bold" style={{ color: highlight ?? "var(--aqt-fg)" }}>
      {value}
    </span>
  </div>
);

// Minimum events with placement data before a distribution / verdict is honest
// (design-book §5/§6 — no scouting verdict on a tiny sample).
const MIN_FINISH_SAMPLE = 5;

interface FinishSegment {
  key: "first" | "second" | "third" | "topHalf" | "bottom";
  labelKey: string;
  color: string;
  count: number;
}

const OverviewCareerList = async ({ profile, tournaments = [] }: Props) => {
  const t = await getTranslations();
  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;
  const closeness = profile.avg_closeness === null ? null : profile.avg_closeness * 100;

  // Finishes distribution from real per-event placements (same source the
  // placement trend uses). count_teams gives an honest top-half / bottom split.
  const placed = tournaments.filter((tr) => tr.placement && tr.count_teams);
  let first = 0;
  let second = 0;
  let third = 0;
  let topHalf = 0;
  let bottom = 0;
  for (const tr of placed) {
    const p = tr.placement;
    if (p === 1) first += 1;
    else if (p === 2) second += 1;
    else if (p === 3) third += 1;
    else if (p <= Math.ceil(tr.count_teams / 2)) topHalf += 1;
    else bottom += 1;
  }
  const totalPlaced = placed.length;
  const segments: FinishSegment[] = [
    { key: "first", labelKey: "users.overview.career.finish.first", color: "var(--aqt-gold)", count: first },
    { key: "second", labelKey: "users.overview.career.finish.second", color: "var(--aqt-silver)", count: second },
    { key: "third", labelKey: "users.overview.career.finish.third", color: "var(--aqt-bronze)", count: third },
    { key: "topHalf", labelKey: "users.overview.career.finish.topHalf", color: "var(--aqt-teal)", count: topHalf },
    { key: "bottom", labelKey: "users.overview.career.finish.bottom", color: "var(--aqt-card-2)", count: bottom }
  ];
  const visibleSegments = segments.filter((s) => s.count > 0);

  const podiumCount = first + second + third;
  const podiumPct = totalPlaced > 0 ? Math.round((podiumCount / totalPlaced) * 100) : 0;
  const showVerdict = totalPlaced >= MIN_FINISH_SAMPLE;

  return (
    <CardSurface flush title={t("users.overview.career.title")} icon={<Medal size={15} />}>
      {totalPlaced > 0 ? (
        <div className="flex flex-col gap-2.5 px-[18px] pb-3 pt-3.5">
          <div className="flex items-center justify-between gap-2">
            <span className="aqt-mono text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
              {t("users.overview.career.finishes")}
            </span>
            <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
              {t("users.overview.career.events", { count: totalPlaced })}
            </span>
          </div>
          <div className="flex h-[8px] w-full overflow-hidden rounded-full border border-[color:var(--aqt-border)]">
            {visibleSegments.map((s) => (
              <div
                key={s.key}
                style={{ width: `${(s.count / totalPlaced) * 100}%`, background: s.color }}
                title={`${t(s.labelKey as Parameters<typeof t>[0])} · ${s.count}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {visibleSegments.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--aqt-fg-muted)]">
                <span className="inline-block h-[7px] w-[7px] rounded-full" style={{ background: s.color }} />
                {t(s.labelKey as Parameters<typeof t>[0])}
                <span className="aqt-tnum font-bold text-[color:var(--aqt-fg)]">{s.count}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <Row label={t("users.overview.career.tournaments")} value={`${profile.tournaments_count}`} />
      <Row
        label={t("users.overview.career.tournamentsWon")}
        value={`${profile.tournaments_won}`}
        highlight={profile.tournaments_won > 0 ? "var(--aqt-amber)" : undefined}
      />
      <Row label={t("users.overview.career.winrate")} value={fmt(winrate, 2, "%")} />
      <Row label={t("users.overview.career.maps")} value={`${profile.maps_won} / ${profile.maps_total}`} />
      {closeness !== null ? (
        <Row
          label={t("users.overview.career.closeness")}
          value={fmt(closeness, 0, "%")}
          title={t("users.overview.career.closenessGlossary")}
        />
      ) : null}
      <Row label={t("users.overview.career.avgPlacement")} value={fmt(profile.avg_placement)} />
      <Row label={t("users.overview.career.avgPlayoffPlace")} value={fmt(profile.avg_playoff_placement)} />
      <Row label={t("users.overview.career.avgGroupPlace")} value={fmt(profile.avg_group_placement, 0)} />

      {showVerdict ? (
        <div
          className="m-[18px] mt-3 rounded-[8px] bg-[color:var(--aqt-card-2)] px-3 py-2.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]"
          style={{ borderLeft: "2px solid var(--aqt-teal)" }}
        >
          {t("users.overview.career.verdictPodium", { pct: podiumPct, count: totalPlaced })}
        </div>
      ) : null}
    </CardSurface>
  );
};

export default OverviewCareerList;
