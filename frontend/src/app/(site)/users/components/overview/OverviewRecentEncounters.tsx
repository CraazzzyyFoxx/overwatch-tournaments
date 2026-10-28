import { getTranslations } from "next-intl/server";
import { ArrowRight } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { CARD_HEAD_LINK, CardSurface } from "@/components/profile/atoms";
import { ScoreCell } from "@/components/match/cells";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { EncounterWithUserStats, UserTournament } from "@/types/user.types";
import { getPlayerSlug } from "@/lib/player";
import {
  encounterPerspective,
  uniqueViewerCharacters
} from "@/app/(site)/users/components/shared/encounter-perspective";

interface Props {
  encounters: EncounterWithUserStats[];
  userId: number;
  userName: string;
  tournaments: UserTournament[];
}

const OverviewRecentEncounters = async ({ encounters, userId, userName, tournaments }: Props) => {
  if (encounters.length === 0) return null;
  const t = await getTranslations();
  const userSlug = getPlayerSlug(userName);
  const teamIdByTournament = new Map(tournaments.map((tour) => [tour.id, tour.team_id]));

  return (
    <CardSurface
      flush
      title={t("users.overview.recent.title")}
      action={
        <HoverPrefetchLink href={`/users/${userSlug}?tab=matches`} className={CARD_HEAD_LINK}>
          {t("users.overview.recent.allMatches")}
          <ArrowRight aria-hidden className="size-3" />
        </HoverPrefetchLink>
      }
    >
      {encounters.map((enc) => {
        const userTeamId = enc.tournament ? teamIdByTournament.get(enc.tournament.id) : undefined;
        const perspective = encounterPerspective(enc, userId, userTeamId);
        const opponent = perspective.opponent?.name ?? t("common.tbd");
        const stage = enc.stage_item?.name ?? enc.stage?.name ?? "";
        const scoreKind = perspective.kind;
        const mapCount = enc.matches?.length ?? 0;
        // Stage is the honest label when the bracket recorded one; the series
        // length is the only thing left to say when it did not.
        const stageLabel = stage || `BO${enc.best_of || "?"}`;
        const context = [enc.tournament?.name, stageLabel, t("users.overview.mapsCount", { count: mapCount })]
          .filter(Boolean)
          .join(" · ");

        // The viewer's unique heroes across this encounter's matches. No popover —
        // match-history heroes have no per-hero user stats (design-book §11).
        const encHeroes = uniqueViewerCharacters(enc);

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
              {encHeroes.length > 0 ? <CatalogEntityStrip entities={encHeroes} size="sm" limit={4} /> : null}
            </span>
            <ScoreCell
              kind={scoreKind}
              value={`${perspective.userScore} - ${perspective.oppScore}`}
              className="min-w-[42px] text-right"
            />
            <MatchLogIndicator hasLogs={enc.has_logs} size={13} className="h-6 w-6" />
          </HoverPrefetchLink>
        );
      })}
    </CardSurface>
  );
};

export default OverviewRecentEncounters;
