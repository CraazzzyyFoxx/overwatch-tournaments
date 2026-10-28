"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ResTag, ScoreCell } from "@/components/match/cells";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { TableCell, TableRow } from "@/components/ui/table";
import { TooltipProvider } from "@/components/ui/tooltip";
import MatchRowBadge from "@/components/match/MatchRowBadge";
import {
  encounterLogEntries,
  encounterPerspective,
  uniqueViewerCharacters
} from "@/app/(site)/users/components/shared/encounter-perspective";
import { GameIcon } from "@/components/workspace/GameIcon";
import { EncounterWithUserStats } from "@/types/user.types";
import { tournamentHref } from "@/lib/tournament/url";

interface MatchRowProps {
  enc: EncounterWithUserStats;
  selfUserId: number;
  showGame?: boolean;
}

const MatchRow = ({ enc, selfUserId, showGame = false }: MatchRowProps) => {
  const router = useRouter();
  const t = useTranslations();
  const { opponent, userScore, oppScore, kind: scoreKind } = encounterPerspective(enc, selfUserId);
  const resKind = scoreKind === "win" ? "w" : scoreKind === "loss" ? "l" : "d";
  const opponentName = opponent?.name;
  const tournamentName = enc.tournament?.name ?? `#${enc.tournament_id}`;
  // `viewer.characters` is already the viewer's characters for each match (the module's eligibility rule is
  // applied server-side from native character facts).
  const heroList = uniqueViewerCharacters(enc);

  const observedMatches = (enc.matches ?? []).filter((m) => m.viewer != null);

  return (
    <TableRow onClick={() => router.push(`/encounters/${enc.id}`)} className="cursor-pointer">
      <TableCell className="px-3.5 py-3">
        <span className="inline-flex max-w-[220px] items-center gap-1.5">
          {showGame ? <GameIcon slug={enc.discipline} /> : null}
          <HoverPrefetchLink
            href={tournamentHref(enc.tournament_id)}
            onClick={(e) => e.stopPropagation()}
            title={tournamentName}
            className="block max-w-[200px] truncate text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-teal)]"
          >
            {tournamentName}
          </HoverPrefetchLink>
        </span>
      </TableCell>
      <TableCell className="px-3.5 py-3 text-[color:var(--aqt-fg-dim)]">
        {(enc.stage_item?.name ?? enc.stage?.name)?.trim() || "—"}
      </TableCell>
      <TableCell className="px-3.5 py-3">
        <span className="inline-flex items-center gap-2">
          <ResTag kind={resKind} />
          <HoverPrefetchLink
            href={`/encounters/${enc.id}`}
            onClick={(e) => e.stopPropagation()}
            className="hover:text-[color:var(--aqt-teal)]"
          >
            {t("common.vs")} {opponentName}
          </HoverPrefetchLink>
        </span>
      </TableCell>
      <TableCell className="px-3.5 py-3">
        <ScoreCell kind={scoreKind} value={`${userScore}-${oppScore}`} />
      </TableCell>
      <TableCell className="px-3.5 py-3">
        <CatalogEntityStrip entities={heroList} size="sm" limit={4} />
      </TableCell>
      <TableCell className="px-3.5 py-3">
        {observedMatches.length > 0 ? (
          <TooltipProvider>
            <span className="inline-flex items-center gap-2">
              {observedMatches.map((m) => (
                <MatchRowBadge key={m.id} match={m} />
              ))}
            </span>
          </TooltipProvider>
        ) : (
          <span className="aqt-tnum text-[color:var(--aqt-fg-faint)]">—</span>
        )}
      </TableCell>
      <TableCell className="aqt-tnum px-3.5 py-3 text-label text-[color:var(--aqt-fg-dim)]">
        {enc.closeness != null ? `${(enc.closeness * 100).toFixed(0)}%` : "—"}
      </TableCell>
      <TableCell className="px-3.5 py-3" onClick={(e) => e.stopPropagation()}>
        <MatchLogIndicator hasLogs={enc.has_logs} logs={encounterLogEntries(enc, t("encounters.match.mapAlt"))} />
      </TableCell>
    </TableRow>
  );
};

export default MatchRow;
