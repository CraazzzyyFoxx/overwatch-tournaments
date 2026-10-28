import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

const SIZE_CLASS = {
  /** Inline chip: table cells, leaderboards. */
  default: "h-5 min-w-5 px-1.5 text-label",
  /** Squares: a profile's tournament list (`md`), its dossier (`lg`/`sm`). */
  sm: "size-7 font-display text-caption",
  md: "size-9 font-display text-ui",
  lg: "size-11 font-display text-title"
} as const;

const TIER_CLASS = {
  gold: "bg-[color:var(--aqt-medal-gold)] text-[color:var(--aqt-medal-gold-fg)]",
  silver: "bg-[color:var(--aqt-medal-silver)] text-[color:var(--aqt-medal-silver-fg)]",
  bronze: "bg-[color:var(--aqt-medal-bronze)] text-[color:var(--aqt-medal-bronze-fg)]",
  default: "bg-[color:var(--aqt-medal-default)] text-[color:var(--aqt-medal-default-fg)]"
} as const;

/**
 * Placement medal. One implementation, driven by the `--aqt-medal-*` tokens.
 *
 * The gold/silver/bronze hex triple used to be written out by hand in the home
 * dashboard, the statistics leaderboards and the OWAL standings — three copies
 * that no workspace theme could reach. A missing placement (`null`, or a
 * non-positive one) draws "—" on the neutral medal. A medal names its tier for
 * a screen reader ("1st place, gold"); the colour alone would be colour-only.
 */
export function PlaceBadge({
  place,
  size = "default",
  className
}: Readonly<{
  place: number | null;
  size?: keyof typeof SIZE_CLASS;
  className?: string;
}>) {
  const t = useTranslations("kit.ui.place");
  const ranked = place != null && place > 0 ? place : null;
  const tier =
    ranked === 1 ? "gold" : ranked === 2 ? "silver" : ranked === 3 ? "bronze" : "default";

  return (
    <span
      role="img"
      aria-label={
        ranked == null
          ? t("none")
          : tier === "default"
            ? t("place", { place: ranked })
            : t(tier, { place: ranked })
      }
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md font-bold leading-none tabular-nums",
        SIZE_CLASS[size],
        TIER_CLASS[tier],
        className
      )}
    >
      {ranked ?? "—"}
    </span>
  );
}
