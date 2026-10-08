import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

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
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  children?: React.ReactNode;
  flush?: boolean;
  className?: string;
  bodyClassName?: string;
  headerClassName?: string;
  /**
   * Element used for `title`. A card IS a page section, so the default is a real
   * `h2` — without it the profile shipped nine visually-titled panels and a
   * single `h1`, leaving screen readers no document outline. Pass `"h3"` for a
   * card nested inside another titled section, `"div"` when the title is only a
   * label (e.g. a picker row) rather than a section name.
   */
  titleAs?: "h2" | "h3" | "div";
}

/**
 * The profile's one level of framing. The title is a mixed-case section
 * heading (`.aqt-pf-title`), never an uppercase label with a decorative icon;
 * everything inside the body stays open — no nested bordered tiles.
 */
export const CardSurface = ({
  title,
  subtitle,
  action,
  children,
  flush,
  className,
  bodyClassName,
  headerClassName,
  titleAs: TitleTag = "h2"
}: CardSurfaceProps) => {
  const hasHead = title !== undefined || subtitle !== undefined || action !== undefined;
  return (
    <div className={cn("aqt-card-surface", className)}>
      {hasHead ? (
        <div className={cn("aqt-card-head", headerClassName)}>
          <div className="flex min-w-0 items-baseline gap-3">
            {title !== undefined ? (
              <TitleTag className="aqt-pf-title truncate">{title}</TitleTag>
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

/**
 * One open KPI: uppercase data label, Onest figure, optional sub line. No box —
 * stats group by whitespace inside their section (design-book "air over
 * boxes"). `color` encodes quality only (e.g. `winrateColor(pct)` or
 * `--aqt-emerald` for a positive delta); never decoration.
 * `children` render under the sub line (e.g. a percentile bar).
 */
export const ProfileStat = ({
  label,
  value,
  sub,
  color,
  size = "lg",
  title,
  className,
  children
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
  size?: "md" | "lg";
  title?: string;
  className?: string;
  children?: React.ReactNode;
}) => (
  <div className={cn("flex min-w-0 flex-col gap-1", className)} title={title}>
    <span className="aqt-tnum truncate text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
      {label}
    </span>
    <span
      className={cn(
        "font-onest font-bold leading-none tabular-nums",
        size === "lg" ? "text-headline" : "text-title"
      )}
      style={{ color: color ?? "var(--aqt-fg)" }}
    >
      {value}
    </span>
    {sub ? <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">{sub}</span> : null}
    {children}
  </div>
);
