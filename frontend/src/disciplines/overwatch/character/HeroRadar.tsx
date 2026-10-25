"use client";

import { useTranslations } from "next-intl";

import type { RadarAxis } from "./hero-stats";
import { formatDelta } from "./utils";

/** The outer ring: twice the average. */
const RADIUS = 70;
/** From the outer ring to an axis label. */
const LABEL_GAP = 12;
/** A side label's width: the longest, "Соло-убийства", runs about 80px at 12px. */
const LABEL_WIDTH = 92;
/** A top or bottom label's height at 12px. */
const LABEL_HEIGHT = 16;

const point = (index: number, count: number, radius: number) => {
  const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
};

const polygon = (fractions: number[]) =>
  fractions
    .map((fraction, index) => {
      const { x, y } = point(index, fractions.length, fraction * RADIUS);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

/**
 * The hero's figures against every player's average on it, in the round. The dashed ring is the average; the
 * player's shape reaches past it where better and inside it where worse — the same gains as the bars, so the
 * outer ring is twice the average and the centre none of it. The labels sit outside the rings at the label size.
 */
const HeroRadar = ({ heroName, axes }: { heroName: string; axes: RadarAxis[] }) => {
  const t = useTranslations();
  const count = axes.length;
  const label = (axis: RadarAxis) => t(`users.heroes.radar.${axis.name}` as Parameters<typeof t>[0]);
  const gains = axes.map((axis) => Math.min(Math.max(1 + axis.delta, 0), 2) / 2);
  const sideReach = Math.max(...axes.map((_, index) => Math.abs(point(index, count, RADIUS).x)));
  const halfWidth = Math.ceil(sideReach + LABEL_GAP + LABEL_WIDTH);
  const halfHeight = RADIUS + LABEL_GAP + LABEL_HEIGHT;
  const summary = t("users.heroes.radarSummary", {
    hero: heroName,
    axes: axes.map((axis) => `${label(axis)} ${formatDelta(axis.delta)}`).join(", ")
  });

  return (
    <figure className="m-0 flex flex-col items-center gap-2">
      <svg
        role="img"
        aria-label={summary}
        viewBox={`${-halfWidth} ${-halfHeight} ${halfWidth * 2} ${halfHeight * 2}`}
        width={halfWidth * 2}
        height={halfHeight * 2}
        className="block h-auto max-w-full"
      >
        <polygon points={polygon(axes.map(() => 1))} style={{ fill: "none", stroke: "var(--aqt-border-2)" }} />
        {axes.map((axis, index) => {
          const end = point(index, count, RADIUS);
          return (
            <line key={axis.name} x1={0} y1={0} x2={end.x} y2={end.y} style={{ stroke: "var(--aqt-border-2)" }} />
          );
        })}
        <polygon
          points={polygon(axes.map(() => 0.5))}
          strokeDasharray="4 3"
          style={{ fill: "none", stroke: "var(--aqt-fg-faint)" }}
        />
        <polygon
          points={polygon(gains)}
          strokeWidth={1.75}
          strokeLinejoin="round"
          style={{ fill: "color-mix(in srgb, var(--aqt-teal) 18%, transparent)", stroke: "var(--aqt-teal)" }}
        />
        {gains.map((gain, index) => {
          const vertex = point(index, count, gain * RADIUS);
          return <circle key={axes[index].name} cx={vertex.x} cy={vertex.y} r={2.5} style={{ fill: "var(--aqt-teal)" }} />;
        })}
        {axes.map((axis, index) => {
          const anchor = point(index, count, RADIUS + LABEL_GAP);
          const side = Math.abs(anchor.x) > 1;
          return (
            <text
              key={axis.name}
              x={anchor.x}
              y={anchor.y}
              textAnchor={side ? (anchor.x > 0 ? "start" : "end") : "middle"}
              dominantBaseline={side ? "middle" : anchor.y < 0 ? "auto" : "hanging"}
              className="text-label"
              style={{ fill: "var(--aqt-fg-muted)" }}
            >
              {label(axis)}
            </text>
          );
        })}
      </svg>
      <figcaption aria-hidden className="flex items-center gap-4 text-label text-[color:var(--aqt-fg-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-[color:var(--aqt-teal)]" />
          {t("users.heroes.you")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 border-t border-dashed border-[color:var(--aqt-fg-faint)]" />
          {t("users.heroes.average")}
        </span>
      </figcaption>
    </figure>
  );
};

export default HeroRadar;
