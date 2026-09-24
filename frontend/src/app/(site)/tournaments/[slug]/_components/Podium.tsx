import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";

import { TeamLogo } from "@/components/TeamName";
import { cn } from "@/lib/utils";
import type { TeamNameInput } from "@/components/TeamName";

export type PodiumTeam = TeamNameInput & {
  id: number;
  /** One line under the name: the champion's roster, a finalist's result. */
  note?: string | null;
  href?: string;
};

export type PodiumProps = {
  first: PodiumTeam;
  second: PodiumTeam;
  /** Absent for a single-elimination bracket, which crowns no third place. */
  third?: PodiumTeam | null;
  className?: string;
};

/**
 * The finished tournament's answer to "who won", first on the overview. Three
 * columns over one hairline, the champion centre and taller; teal — the page's
 * one accent, meaning "the winner" here — marks only the champion. No medal
 * hues, no boxes: the place label and the size difference carry the order.
 */
export function Podium({ first, second, third, className }: Readonly<PodiumProps>) {
  const t = useTranslations();
  const tile = (team: PodiumTeam, place: 1 | 2 | 3) => {
    const champion = place === 1;
    const body = (
      <>
        <span
          className={cn(
            "text-label uppercase tracking-label",
            champion ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          {t(`tournamentDetail.podium.place${place}`)}
        </span>
        <TeamLogo team={team} size={champion ? "xl" : "md"} className="mx-auto mt-3" />
        <span
          className={cn(
            "mt-2 block truncate font-onest font-bold leading-tight",
            champion ? "text-[26px]" : "text-base"
          )}
          title={team.name}
        >
          {team.name}
        </span>
        {team.note ? (
          <span className="mt-1 block text-label leading-snug text-[color:var(--aqt-fg-muted)]">
            {team.note}
          </span>
        ) : null}
      </>
    );
    const classes = cn(
      "block border-t-2 px-3 pb-2 text-center",
      champion ? "border-[color:var(--aqt-teal)] pt-4" : "border-[color:var(--aqt-border)] pt-3"
    );
    return team.href ? (
      <HoverPrefetchLink href={team.href} className={cn(classes, "transition-colors hover:text-[color:var(--aqt-teal)]")}>
        {body}
      </HoverPrefetchLink>
    ) : (
      <div className={classes}>{body}</div>
    );
  };

  return (
    <div
      className={cn("grid items-start gap-2", third ? "grid-cols-[1fr_1.2fr_1fr]" : "grid-cols-[1fr_1.2fr]", className)}
      role="list"
      aria-label={t("tournamentDetail.podium.label")}
    >
      <div role="listitem">{tile(second, 2)}</div>
      <div role="listitem">{tile(first, 1)}</div>
      {third ? <div role="listitem">{tile(third, 3)}</div> : null}
    </div>
  );
}
