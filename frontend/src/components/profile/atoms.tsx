import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Card, CardTitle } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { ResTag } from "@/components/match/cells";

// ─── Profile-only atoms (no cross-page consumer; kept local) ──────────────────

export type FormResult = "W" | "L" | "D";

export const FormStreak = ({ results, className }: { results: FormResult[]; className?: string }) => {
  const t = useTranslations();
  return (
    <span className={cn("inline-flex gap-[3px]", className)} aria-label={t("users.profile.atoms.recentForm")}>
      {results.map((r, i) => (
        <ResTag key={i} kind={r === "W" ? "w" : r === "L" ? "l" : "d"} />
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

/** The "All N →" link in a `CardSurface` head: plain mixed-case teal caption text. */
export const CARD_HEAD_LINK =
  "inline-flex items-center gap-1 whitespace-nowrap text-caption font-medium text-[color:var(--aqt-teal)] underline-offset-3 hover:underline";

/**
 * The profile's one level of framing. The title is a mixed-case section
 * heading (`CardTitle`, Onest), never an uppercase label with a decorative icon;
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
    <Card className={cn("overflow-hidden", className)}>
      {hasHead ? (
        <div
          className={cn(
            "flex items-center justify-between gap-2.5 border-b border-[color:var(--aqt-border)] px-4.5 py-3.5",
            headerClassName
          )}
        >
          <div className="flex min-w-0 items-baseline gap-3">
            {title !== undefined ? (
              <CardTitle asChild className="truncate font-display text-[color:var(--aqt-fg)]">
                <TitleTag>{title}</TitleTag>
              </CardTitle>
            ) : null}
            {subtitle !== undefined ? (
              <span className="truncate font-[family-name:var(--aqt-data)] text-label text-[color:var(--aqt-fg-dim)]">
                {subtitle}
              </span>
            ) : null}
          </div>
          {action !== undefined ? <div className="flex items-center gap-2">{action}</div> : null}
        </div>
      ) : null}
      <div className={cn(flush ? "p-0" : "p-4.5", bodyClassName)}>{children}</div>
    </Card>
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
    <Eyebrow className="aqt-tnum truncate">{label}</Eyebrow>
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

/** One cell of a dossier's hairline summary strip: uppercase label over an Onest figure. `color` encodes quality. */
export const SummaryCellBox = ({
  label,
  value,
  color
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  color?: string;
}) => (
  <div className="flex flex-col gap-1 border-l border-[color:var(--aqt-border)] px-3 py-2.5 first:border-l-0">
    <Eyebrow className="aqt-tnum">{label}</Eyebrow>
    <span className="aqt-display aqt-tnum text-base font-bold leading-none" style={{ color: color ?? "var(--aqt-fg)" }}>
      {value}
    </span>
  </div>
);
