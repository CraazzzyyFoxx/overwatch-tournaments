import React from "react";
import { cn } from "@/lib/utils";

export type AqtRoleKey = "tank" | "damage" | "support";

const ROLE_NORMALIZED: Record<string, AqtRoleKey> = {
  tank: "tank",
  Tank: "tank",
  damage: "damage",
  Damage: "damage",
  dps: "damage",
  DPS: "damage",
  support: "support",
  Support: "support",
  healer: "support",
  Healer: "support"
};

export const normalizeRole = (role: string | null | undefined): AqtRoleKey | null => {
  if (!role) return null;
  return ROLE_NORMALIZED[role] ?? ROLE_NORMALIZED[role.toLowerCase()] ?? null;
};

interface DivisionHexProps {
  division: number;
  role?: string | null;
  variant?: AqtRoleKey | "amber" | "violet" | "gold" | "gray";
  size?: number;
  className?: string;
}

export const DivisionHex = ({ division, role, variant, size = 30, className }: DivisionHexProps) => {
  const normalized = variant ?? normalizeRole(role) ?? "gray";
  const bgClass = `aqt-bg-${normalized}`;
  const height = size * 1.13;
  return (
    <span
      className={cn("relative inline-flex items-center justify-center flex-shrink-0", className)}
      style={{ width: size, height }}
    >
      <span className={cn("absolute inset-0 aqt-hex-shape", bgClass)} />
      <span
        className="relative aqt-display font-extrabold leading-none"
        style={{
          fontSize: size * 0.45,
          color: "hsl(220 30% 8%)"
        }}
      >
        {division}
      </span>
    </span>
  );
};

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

export const heroVariantFromRole = (role: string | null | undefined): AqtRoleKey => {
  return normalizeRole(role) ?? "damage";
};

export const heroInitials = (name: string): string => {
  if (!name) return "?";
  const parts = name.replace(/[^A-Za-zА-Яа-я0-9]/g, " ").trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
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

export type StageKind = "group" | "playoffs" | "finals" | "default";

export const StagePill = ({ children, kind = "default", className }: { children: React.ReactNode; kind?: StageKind; className?: string }) => {
  return (
    <span className={cn("aqt-stage-pill", kind !== "default" && kind, className)}>{children}</span>
  );
};

export type ResTagKind = "w" | "l" | "d";

export const ResTag = ({ kind, className }: { kind: ResTagKind; className?: string }) => (
  <span className={cn("aqt-res-tag", kind, className)}>{kind.toUpperCase()}</span>
);

export type ScoreKind = "win" | "loss" | "draw";

export const ScoreCell = ({ kind, value, className }: { kind: ScoreKind; value: string; className?: string }) => (
  <span className={cn("aqt-score-cell", kind, className)}>{value}</span>
);

export type MvpRank = "gold" | "silver" | "bronze" | "default";

export const MvpPill = ({ rank, label, className }: { rank: MvpRank; label: string; className?: string }) => (
  <span className={cn("aqt-mvp-pill", rank !== "default" && rank, className)}>{label}</span>
);

/** Map a 1-based per-match performance placement to an MvpPill rank. */
export const mvpRank = (performance: number | null | undefined): MvpRank => {
  if (performance === 1) return "gold";
  if (performance === 2) return "silver";
  if (performance === 3) return "bronze";
  return "default";
};

/** English ordinal for a positive integer (1 → "1st", 2 → "2nd", …). */
export const ordinal = (n: number): string => {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
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

interface SparkPoint {
  label: string;
  placement: number;
}

export const PlacementSpark = ({ data, max }: { data: SparkPoint[]; max?: number }) => {
  if (!data.length) return null;
  const top = max ?? Math.max(...data.map((d) => d.placement), 1);
  return (
    <div className="aqt-place-spark">
      {data.map((d, i) => {
        const heightPct = Math.max(6, 100 - (d.placement / top) * 100);
        const cls = d.placement === 1 ? "first" : d.placement <= 3 ? "podium" : "";
        return (
          <div key={i} className={cn("aqt-col", cls)} title={`#${d.placement} · ${d.label}`}>
            <span className="aqt-val">#{d.placement}</span>
            <div className="aqt-bar" style={{ height: `${heightPct}%` }} />
            <span className="aqt-lbl">{d.label}</span>
          </div>
        );
      })}
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
