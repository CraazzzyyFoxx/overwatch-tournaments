import React from "react";
import { cn } from "@/lib/utils";
import { type AqtRoleKey } from "@/components/hero/heroRole";
import { type ScoreKind } from "@/components/match/cells";

// ─── Shared primitives promoted to global components/ (re-exported here so
//     existing profile imports keep working; new pages import from the homes). ──
export { normalizeRole, heroVariantFromRole, heroInitials } from "@/components/hero/heroRole";
export type { AqtRoleKey } from "@/components/hero/heroRole";
export { StagePill, ResTag, ScoreCell, MvpPill, mvpRank, ordinal } from "@/components/match/cells";
export type { StageKind, ResTagKind, ScoreKind, MvpRank } from "@/components/match/cells";
export { DivisionHex } from "@/components/stats/DivisionHex";
export { PlacementSpark } from "@/components/stats/PlacementSpark";

// ─── Profile-only atoms (no cross-page consumer; kept local) ──────────────────

interface HeroAvatarProps {
  initials: string;
  variant?: AqtRoleKey | "amber" | "violet" | "rose" | "cyan" | "lime";
  size?: "sm" | "md" | "lg";
  title?: string;
  className?: string;
}

export const HeroAvatar = ({ initials, variant = "damage", size = "md", title, className }: HeroAvatarProps) => {
  return (
    <span
      className={cn("aqt-hero-av", size === "sm" && "sm", size === "lg" && "lg", variant, className)}
      title={title}
    >
      {initials}
    </span>
  );
};

export type FormResult = "W" | "L" | "D";

export const FormStreak = ({ results, className }: { results: FormResult[]; className?: string }) => {
  return (
    <span className={cn("inline-flex gap-[3px]", className)} aria-label="Recent form">
      {results.map((r, i) => (
        <span key={i} className={cn("aqt-form-chip", r === "W" && "w", r === "L" && "l", r === "D" && "d")}>
          {r}
        </span>
      ))}
    </span>
  );
};

export const PipRow = ({ results, tall = false, className }: { results: ScoreKind[]; tall?: boolean; className?: string }) => (
  <span className={cn("inline-flex gap-[3px]", className)}>
    {results.map((r, i) => (
      <span key={i} className={cn(tall ? "aqt-pip-tall" : "aqt-pip", r === "win" && "win", r === "loss" && "loss", r === "draw" && "draw")} />
    ))}
  </span>
);

interface CardSurfaceProps {
  title?: React.ReactNode;
  icon?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  children?: React.ReactNode;
  flush?: boolean;
  className?: string;
  bodyClassName?: string;
  headerClassName?: string;
}

export const CardSurface = ({
  title,
  icon,
  subtitle,
  action,
  children,
  flush,
  className,
  bodyClassName,
  headerClassName
}: CardSurfaceProps) => {
  const hasHead = title !== undefined || subtitle !== undefined || action !== undefined;
  return (
    <div className={cn("aqt-card-surface", className)}>
      {hasHead ? (
        <div className={cn("aqt-card-head", headerClassName)}>
          <div className="flex items-center gap-3 min-w-0">
            {title !== undefined ? (
              <div className="aqt-card-title">
                {icon ? <span className="aqt-card-title-ic">{icon}</span> : null}
                <span className="truncate">{title}</span>
              </div>
            ) : null}
            {subtitle !== undefined ? <span className="aqt-card-sub truncate">{subtitle}</span> : null}
          </div>
          {action !== undefined ? <div className="flex items-center gap-2">{action}</div> : null}
        </div>
      ) : null}
      <div className={cn("aqt-card-body", flush && "aqt-flush", bodyClassName)}>{children}</div>
    </div>
  );
};

interface RolePyramidSegment {
  role: AqtRoleKey;
  maps: number;
  label: string;
}

export const RolePyramid = ({ segments }: { segments: RolePyramidSegment[] }) => {
  const total = segments.reduce((sum, s) => sum + s.maps, 0);
  if (total === 0) return null;
  return (
    <div className="aqt-pyramid-bar">
      {segments.map((seg) =>
        seg.maps > 0 ? (
          <div
            key={seg.role}
            className={cn("aqt-pyramid-seg", `aqt-bg-${seg.role}`)}
            style={{ width: `${(seg.maps / total) * 100}%` }}
            title={`${seg.label}: ${seg.maps} maps`}
          >
            {seg.label}
          </div>
        ) : null
      )}
    </div>
  );
};
