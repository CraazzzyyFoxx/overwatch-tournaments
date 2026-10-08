import { getTranslations } from "next-intl/server";
import { ArrowRight } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { HeroStrip } from "@/components/hero/HeroImage";
import { EncounterWithUserStats, UserTournament } from "@/types/user.types";
import { Hero } from "@/types/hero.types";
import { cn } from "@/lib/utils";
import { getPlayerSlug } from "@/lib/player";

interface Props {
  encounters: EncounterWithUserStats[];
  userName: string;
  tournaments: UserTournament[];
}

const OverviewRecentEncounters = async ({ encounters, userName, tournaments }: Props) => {
  if (encounters.length === 0) return null;
  const t = await getTranslations();
  const userSlug = getPlayerSlug(userName);
  const teamIdByTournament = new Map(tournaments.map((tour) => [tour.id, tour.team_id]));

  return (
    <CardSurface
      flush
      title={t("users.overview.recent.title")}
      action={
        <HoverPrefetchLink href={`/users/${userSlug}?tab=matches`} className="aqt-pf-link">
          {t("users.overview.recent.allMatches")}
          <ArrowRight aria-hidden className="size-3" />
        </HoverPrefetchLink>
      }
    >
      {encounters.map((enc) => {
        const userTeamId = enc.tournament ? teamIdByTournament.get(enc.tournament.id) : undefined;
        const isUserHome = userTeamId != null && enc.home_team_id === userTeamId;
        const opponent =
          (isUserHome ? enc.away_team?.name : enc.home_team?.name) ??
          (isUserHome ? t("common.awayTeam") : t("common.homeTeam"));
        const stage = enc.stage_item?.name ?? enc.stage?.name ?? "";
        const score = enc.score;
        const scoreKind =
          score.home === score.away ? "draw" : (isUserHome ? score.home > score.away : score.away > score.home) ? "win" : "loss";
        const mapCount = enc.matches?.length ?? 0;
        // Stage is the honest label when the bracket recorded one; the series
        // length is the only thing left to say when it did not.
        const stageLabel = stage || `BO${enc.best_of || "?"}`;
        const context = [enc.tournament?.name, stageLabel, t("users.overview.mapsCount", { count: mapCount })]
          .filter(Boolean)
          .join(" · ");

        // The viewer's unique heroes across this encounter's matches
        // (match `heroes` are already the viewer's). Deduped by image/name;
        // no popover — match-history heroes have no per-hero user stats
        // (design-book §11).
        const heroMap = new Map<string, Hero>();
        for (const m of enc.matches ?? []) {
          for (const h of m.heroes ?? []) {
            const heroKey = h.image_path || h.name;
            if (!heroMap.has(heroKey)) heroMap.set(heroKey, h);
          }
        }
        const encHeroes = Array.from(heroMap.values());

        return (
          <HoverPrefetchLink
            key={enc.id}
            href={`/encounters/${enc.id}`}
            className="grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3 transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)] sm:grid-cols-[1fr_auto_auto_auto]"
          >
            <div className="flex min-w-0 flex-col gap-0.5 leading-tight">
              <div className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">
                {t("common.vs")} {opponent}
              </div>
              <div className="truncate text-label text-[color:var(--aqt-fg-dim)]" title={context}>
                {context}
              </div>
            </div>
            <span className="hidden items-center sm:inline-flex">
              {encHeroes.length > 0 ? <HeroStrip heroes={encHeroes} size="sm" limit={4} /> : null}
            </span>
            <span
              className={cn(
                "aqt-tnum min-w-[42px] text-right text-base font-bold",
                scoreKind === "win" && "text-[color:var(--aqt-emerald)]",
                scoreKind === "loss" && "text-[color:var(--aqt-rose)]",
                scoreKind === "draw" && "text-[color:var(--aqt-amber)]"
              )}
            >
              {score.home} - {score.away}
            </span>
            <MatchLogIndicator hasLogs={enc.has_logs} size={13} className="h-6 w-6" />
          </HoverPrefetchLink>
        );
      })}
    </CardSurface>
  );
};

export default OverviewRecentEncounters;
