"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";
import { EncounterWithUserStats } from "@/types/user.types";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { ScoreCell, type ScoreKind } from "@/components/match/cells";
import MatchRowBadge from "@/components/match/MatchRowBadge";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import {
  encounterLogEntries,
  encounterPerspective,
  mapKind,
  uniqueViewerCharacters
} from "@/app/(site)/users/components/shared/encounter-perspective";
import { TooltipProvider } from "@/components/ui/tooltip";

// ─── Encounter row (expanded matches table) ─────────────────────────────────────

const scoreAccent: Record<ScoreKind, string> = {
  win: "var(--aqt-emerald)",
  loss: "var(--aqt-rose)",
  draw: "var(--aqt-amber)"
};

const EncounterRow = ({
  enc,
  selfUserId,
  teamId
}: {
  enc: EncounterWithUserStats;
  selfUserId: number;
  teamId: number;
}) => {
  const t = useTranslations();
  const { own, opponent: opponentSeat, userScore, oppScore, kind: scoreKind } = encounterPerspective(
    enc,
    selfUserId,
    teamId
  );
  const opponent = opponentSeat?.name;

  // Per-map result pips (from the user's team perspective).
  const mapPips: ScoreKind[] = (enc.matches ?? []).map((m) => mapKind(m, own));
  const mapsWon = mapPips.filter((k) => k === "win").length;
  const mapsLost = mapPips.filter((k) => k === "loss").length;

  const heroes = uniqueViewerCharacters(enc);

  const stageLabel = enc.stage_item?.name ?? enc.stage?.name ?? enc.name ?? "—";

  return (
    <HoverPrefetchLink
      href={`/encounters/${enc.id}`}
      className="-mx-2 grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-lg border-b border-[color:var(--aqt-border)] px-2 py-2.5 text-ui transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)] md:grid-cols-[1fr_auto_auto_auto_auto_auto_auto]"
    >
      {/* Stage + opponent */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate font-medium text-[color:var(--aqt-fg)]">{opponent ?? enc.name}</span>
        <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-dim)]">{stageLabel}</span>
      </div>

      {/* Heroes */}
      <div className="hidden items-center md:flex">
        <CatalogEntityStrip entities={heroes} size="sm" limit={6} />
      </div>

      {/* MVP pills (per map) — hover shows the map it was earned on */}
      <div className="hidden items-center gap-1 md:flex">
        <TooltipProvider>
          {(enc.matches ?? []).map((m) => (
            <MatchRowBadge key={m.id} match={m} />
          ))}
        </TooltipProvider>
      </div>

      {/* Closeness */}
      {enc.closeness != null ? (
        <span className="aqt-tnum hidden text-caption text-[color:var(--aqt-fg-dim)] md:block">
          {(enc.closeness * 100).toFixed(0)}%
        </span>
      ) : (
        <span className="hidden md:block" />
      )}

      {/* Per-map result pips */}
      {mapPips.length > 0 ? (
        <div
          className="hidden items-center gap-1 md:flex"
          aria-label={t("users.tournaments.dossier.mapResults", { won: mapsWon, lost: mapsLost })}
        >
          {mapPips.map((kind, i) => (
            <span
              key={i}
              className="h-1.5 w-1.5 rounded-[2px]"
              style={{ background: scoreAccent[kind] }}
              aria-hidden="true"
            />
          ))}
        </div>
      ) : (
        <span className="hidden md:block" />
      )}

      {/* Score */}
      <ScoreCell kind={scoreKind} value={`${userScore} – ${oppScore}`} className="min-w-[52px] text-right" />

      {/* Logs — click shield, not a control: the whole row is one link, so a
          click on the log badge must not navigate. No keyboard twin by design:
          this only catches clicks on the indicator's non-focusable `<span>`
          variants; its focusable ones stop propagation themselves. */}
      <div
        role="presentation"
        className="hidden justify-end md:flex"
        onClick={(e) => e.preventDefault()}
      >
        <MatchLogIndicator hasLogs={enc.has_logs} logs={encounterLogEntries(enc, t("encounters.match.mapAlt"))} />
      </div>
    </HoverPrefetchLink>
  );
};

export default EncounterRow;
