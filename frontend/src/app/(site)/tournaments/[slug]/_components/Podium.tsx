import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";

import { TeamLogo } from "@/components/TeamName";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { PlaceBadge } from "@/components/ui/place-badge";
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
 * The finished tournament's answer to "who won", leading the overview at full
 * width. Three columns stepped like a podium: the champion in the centre,
 * larger and a step higher; second and third a step down on either side. Each
 * place carries its medal (DESIGN §2: medals mark places 1–3 of a finished
 * competition) beside the word, so the order reads by colour, size and text.
 */
export function Podium({ first, second, third, className }: Readonly<PodiumProps>) {
  const t = useTranslations();
  const tile = (team: PodiumTeam, place: 1 | 2 | 3) => {
    const champion = place === 1;
    const body = (
      <>
        <span className="inline-flex items-center gap-2">
          <PlaceBadge place={place} size={champion ? "md" : "sm"} />
          <span className={cn(eyebrowClass(), champion && "text-[color:var(--aqt-fg)]")}>
            {t(`tournamentDetail.podium.place${place}`)}
          </span>
        </span>
        <TeamLogo team={team} size={champion ? "xl" : "lg"} className="mx-auto mt-4" />
        <span
          className={cn(
            "mt-3 block truncate font-onest font-bold",
            champion ? "text-headline" : "text-heading"
          )}
          title={team.name}
        >
          {team.name}
        </span>
        {team.note ? (
          <span className="mt-1 block text-label leading-snug wrap-break-word text-[color:var(--aqt-fg-muted)]">
            {team.note}
          </span>
        ) : null}
      </>
    );
    // The step: the runners-up start lower, from `sm` where the three stand
    // side by side.
    const classes = cn("block px-2 py-1 text-center", !champion && "sm:mt-8");
    return team.href ? (
      <HoverPrefetchLink href={team.href} className={cn(classes, "transition-colors hover:text-[color:var(--aqt-teal)]")}>
        {body}
      </HoverPrefetchLink>
    ) : (
      <div className={classes}>{body}</div>
    );
  };

  // Below `sm` the champion takes a row of its own and the runners-up share
  // the next: three columns of a 390px screen truncated every name.
  return (
    <div
      className={cn(
        "grid grid-cols-2 items-start gap-x-2 gap-y-5",
        third
          ? "sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)]"
          : "sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]",
        className
      )}
      role="list"
      aria-label={t("tournamentDetail.podium.label")}
    >
      <div role="listitem" className={third ? undefined : "col-span-2 sm:col-span-1"}>
        {tile(second, 2)}
      </div>
      <div role="listitem" className="order-first col-span-2 sm:order-none sm:col-span-1">
        {tile(first, 1)}
      </div>
      {third ? <div role="listitem">{tile(third, 3)}</div> : null}
    </div>
  );
}
