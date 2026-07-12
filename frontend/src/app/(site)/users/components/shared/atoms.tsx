import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

// ─── Shared primitives promoted to global components/ (re-exported here so
//     existing profile imports keep working; new pages import from the homes). ──
export { normalizeRole, heroVariantFromRole, heroInitials } from "@/components/hero/heroRole";
export type { AqtRoleKey } from "@/components/hero/heroRole";
export { StagePill, ResTag, ScoreCell, MvpPill, mvpRank, ordinal } from "@/components/match/cells";
export type { StageKind, ResTagKind, ScoreKind, MvpRank } from "@/components/match/cells";
export { DivisionHex } from "@/components/stats/DivisionHex";
export { PlacementSpark } from "@/components/stats/PlacementSpark";

// ─── Profile-only atoms (no cross-page consumer; kept local) ──────────────────

export type FormResult = "W" | "L" | "D";

export const FormStreak = ({ results, className }: { results: FormResult[]; className?: string }) => {
  const t = useTranslations();
  return (
    <span className={cn("inline-flex gap-[3px]", className)} aria-label={t("users.profile.atoms.recentForm")}>
      {results.map((r, i) => (
        <span key={i} className={cn("aqt-form-chip", r === "W" && "w", r === "L" && "l", r === "D" && "d")}>
          {r}
        </span>
      ))}
    </span>
  );
};

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
