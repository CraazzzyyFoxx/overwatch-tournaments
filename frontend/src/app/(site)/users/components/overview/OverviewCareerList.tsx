import { getTranslations } from "next-intl/server";
import { UserProfile, UserTournament } from "@/types/user.types";
import { CardSurface, ProfileStat } from "@/app/(site)/users/components/shared/atoms";
import { tournamentTag } from "@/app/(site)/users/components/shared/list-utils";

interface Props {
  profile: UserProfile;
  /** Full tournament list (already fetched by the page) — the only source with
   *  per-event `placement` + `count_teams`, which drives the finishes bar and
   *  the placement trend. */
  tournaments?: UserTournament[];
}

const fmt = (value: number | null | undefined, digits = 2, suffix = "") => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
};

interface FinishSegment {
  key: "first" | "second" | "third" | "topHalf" | "bottom";
  labelKey: string;
  color: string;
  count: number;
}

// ─── Placement trend ─────────────────────────────────────────────────────────
// Chart drawing band inside the track (percent of height); leaves head-room for
// the "#N" value labels above the top-most dot and clearance at the bottom.
const TREND_LIMIT = 12;
const Y_TOP = 16;
const Y_BOTTOM = 86;

type Shape = "podium" | "mid" | "bottom";

interface TrendPoint {
  /** Tournament id — the dot/tick key: the series is filtered and sliced from
   *  the career list, so a positional key would follow the slot, not the event. */
  id: number;
  /** Compact axis tick ("T42"), or null when the name yields no usable handle. */
  label: string | null;
  /** Full tournament name — the hover title, so the tick can stay terse. */
  name: string;
  placement: number;
  xFrac: number;
  yPct: number;
  shape: Shape;
  color: string;
}

const podiumColor = (placement: number): string =>
  placement === 1 ? "var(--aqt-gold)" : placement === 2 ? "var(--aqt-silver)" : "var(--aqt-bronze)";

const renderDot = (p: TrendPoint) => {
  if (p.shape === "podium") {
    return (
      <span
        className="block rounded-full"
        style={{ width: 11, height: 11, background: p.color, boxShadow: "0 0 0 2px hsl(0 0% 100% / 0.3)" }}
        aria-hidden
      />
    );
  }
  if (p.shape === "bottom") {
    return (
      <span
        className="block rounded-full"
        style={{ width: 10, height: 10, background: "var(--aqt-bg)", border: "2px solid var(--aqt-rose)" }}
        aria-hidden
      />
    );
  }
  return <span className="block rounded-full" style={{ width: 9, height: 9, background: "var(--aqt-teal)" }} aria-hidden />;
};

const OverviewCareerList = async ({ profile, tournaments = [] }: Props) => {
  const t = await getTranslations();
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
    { key: "bottom", labelKey: "users.overview.career.finish.bottom", color: "var(--aqt-fg-faint)", count: bottom }
  ];
  const visibleSegments = segments.filter((s) => s.count > 0);

  // Deliberately NOT the hero's numbers again. The header already leads with
  // tournaments, map winrate, maps won/total and average placement. What the
  // header cannot show is *depth* — groups versus playoffs, how close the games
  // were, and how many were actually won.
  const stats = [
    {
      key: "won",
      label: t("users.overview.career.tournamentsWon"),
      value: `${profile.tournaments_won}`,
      color: profile.tournaments_won > 0 ? "var(--aqt-gold)" : undefined
    },
    { key: "avgGroup", label: t("users.overview.career.avgGroupPlace"), value: fmt(profile.avg_group_placement, 0) },
    { key: "avgPlayoff", label: t("users.overview.career.avgPlayoffPlace"), value: fmt(profile.avg_playoff_placement) },
    ...(closeness !== null
      ? [
          {
            key: "closeness",
            label: t("users.overview.career.closeness"),
            value: fmt(closeness, 0, "%"),
            title: t("users.overview.career.closenessGlossary")
          }
        ]
      : [])
  ] as { key: string; label: string; value: string; color?: string; title?: string }[];

  // Placement trend: the most recent events that carry a placement, oldest-first
  // so the line reads left → right in time.
  const recent = placed.slice(0, TREND_LIMIT).reverse();
  const placements = recent.map((tour) => tour.placement);
  const fieldMax = recent.length > 0 ? Math.max(...recent.map((tour) => tour.count_teams), 1) : 1;
  const best = recent.length > 0 ? Math.min(...placements) : null;
  const worst = recent.length > 0 ? Math.max(...placements) : null;
  const median = recent.length > 0 ? [...placements].sort((a, b) => a - b)[Math.floor(placements.length / 2)] : null;
  const n = recent.length;
  const points: TrendPoint[] = recent.map((tour, i) => {
    const placement = tour.placement;
    const yFrac = fieldMax > 1 ? Math.min(1, Math.max(0, (placement - 1) / (fieldMax - 1))) : 0;
    const shape: Shape =
      placement <= 3 ? "podium" : placement > Math.ceil(tour.count_teams / 2) ? "bottom" : "mid";
    return {
      id: tour.id,
      label: tournamentTag(tour.name),
      name: tour.name,
      placement,
      xFrac: n > 1 ? i / (n - 1) : 0.5,
      yPct: Y_TOP + yFrac * (Y_BOTTOM - Y_TOP),
      shape,
      color: shape === "podium" ? podiumColor(placement) : shape === "mid" ? "var(--aqt-teal)" : "var(--aqt-rose)"
    };
  });
  const polyPoints = points.map((p) => `${(p.xFrac * 100).toFixed(2)},${p.yPct.toFixed(2)}`).join(" ");

  return (
    <CardSurface title={t("users.overview.career.title")}>
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
          {stats.map((stat) => (
            <ProfileStat key={stat.key} label={stat.label} value={stat.value} color={stat.color} title={stat.title} />
          ))}
        </div>

        {totalPlaced > 0 ? (
          <div className="flex flex-col gap-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.career.finishes")}
              </span>
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.career.placements", { count: totalPlaced })}
              </span>
            </div>
            <div className="flex h-[8px] w-full overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]" aria-hidden>
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
                <span key={s.key} className="inline-flex items-center gap-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                  <span className="inline-block h-[7px] w-[7px] rounded-full" style={{ background: s.color }} aria-hidden />
                  {t(s.labelKey as Parameters<typeof t>[0])}
                  <span className="aqt-tnum font-bold text-[color:var(--aqt-fg)]">{s.count}</span>
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {points.length > 0 ? (
          <div className="flex flex-col gap-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span
                className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                title={t("users.overview.placement.hint")}
              >
                {t("users.overview.placement.title")}
              </span>
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.placement.subtitle", { count: n })}
              </span>
            </div>

            <div>
              <div className="relative h-[112px] overflow-visible">
                <svg
                  className="absolute inset-0 h-full w-full overflow-visible"
                  viewBox="0 0 100 100"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  {n > 1 ? (
                    <polyline
                      points={polyPoints}
                      fill="none"
                      stroke="var(--aqt-teal)"
                      strokeOpacity={0.6}
                      strokeWidth={1.5}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      vectorEffect="non-scaling-stroke"
                    />
                  ) : null}
                </svg>
                {points.map((p) => (
                  <div
                    key={p.id}
                    className="absolute"
                    style={{
                      left: `${(p.xFrac * 100).toFixed(2)}%`,
                      top: `${p.yPct.toFixed(2)}%`,
                      transform: "translate(-50%, -50%)"
                    }}
                    title={`#${p.placement} · ${p.name}`}
                  >
                    <div className="relative flex items-center justify-center">
                      <span className="aqt-tnum absolute bottom-full left-1/2 mb-[3px] -translate-x-1/2 whitespace-nowrap text-label text-[color:var(--aqt-fg-muted)]">
                        #{p.placement}
                      </span>
                      {renderDot(p)}
                    </div>
                  </div>
                ))}
              </div>
              <div className="relative mt-1 h-[13px]">
                {points.map((p) =>
                  p.label ? (
                    <span
                      key={p.id}
                      className="aqt-tnum absolute -translate-x-1/2 whitespace-nowrap text-label text-[color:var(--aqt-fg-faint)]"
                      style={{ left: `${(p.xFrac * 100).toFixed(2)}%` }}
                      title={p.name}
                    >
                      {p.label}
                    </span>
                  ) : null
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-label text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block rounded-full"
                  style={{ width: 10, height: 10, background: "var(--aqt-gold)", boxShadow: "0 0 0 1.5px hsl(0 0% 100% / 0.3)" }}
                  aria-hidden
                />
                {t("users.overview.placement.legend.podium")}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block rounded-full" style={{ width: 9, height: 9, background: "var(--aqt-teal)" }} aria-hidden />
                {t("users.overview.placement.legend.mid")}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block rounded-full"
                  style={{ width: 9, height: 9, background: "var(--aqt-bg)", border: "2px solid var(--aqt-rose)" }}
                  aria-hidden
                />
                {t("users.overview.placement.legend.bottom")}
              </span>
            </div>

            <div className="flex justify-between border-t border-[color:var(--aqt-border)] pt-2.5 text-label text-[color:var(--aqt-fg-muted)]">
              <span>
                {t("users.overview.placement.best")}{" "}
                <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">#{best}</span>
              </span>
              <span>
                {t("users.overview.placement.median")}{" "}
                <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">#{median}</span>
              </span>
              <span>
                {t("users.overview.placement.worst")}{" "}
                <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">#{worst}</span>
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </CardSurface>
  );
};

export default OverviewCareerList;
