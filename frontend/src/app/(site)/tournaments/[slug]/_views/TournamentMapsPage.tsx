"use client";

import { useQuery } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterChip } from "@/components/ui/filter-chip";
import Image from "@/components/ui/image";
import { useQueryParams } from "@/hooks/useQueryParams";
import { isEncounterCompleted } from "@/lib/encounter/status";
import { tournamentEncountersQueryOptions } from "@/lib/tournament/encounters-query";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type { Tournament } from "@/types/tournament.types";

import { MapCard } from "../_components/MapCard";
import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMapsSkeleton } from "../_components/TournamentSkeletons";
import { useTournamentMapPool, type MapPoolScopeView } from "../_hooks/useTournamentMapPool";
import { CardColumns } from "./_components/OverviewCards";
import { balanceColumns } from "./tournamentInsights.model";

/** What was played where: `<stageId>:<round | all>:<map position, 0 = any>` → map id → times. */
type PlayedIndex = Map<string, Map<number, number>>;

/**
 * The map pool. Each stage's rounds in two even columns; every slot names its mode and shows its candidates as short
 * strips, three abreast at any width. Once maps are played, each strip carries how often it came up in that slot and
 * the ones that never did step back.
 */
export default function TournamentMapsPage({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const tp = useTranslations("tournamentDetail");
  const { searchParams, setParams } = useQueryParams();
  const mapPool = useTournamentMapPool(tournament.id, tournament.discipline);
  const encountersQuery = useQuery(tournamentEncountersQueryOptions(tournament));

  if (mapPool.isError && mapPool.pool.total === 0) {
    return <TournamentPageState state="initial-error" onRetry={() => mapPool.refetch()} />;
  }
  if (mapPool.isPending) return <TournamentMapsSkeleton />;

  // Each played map counts for its round and for its stage, at its own position and at "any" (a pool-mode round).
  const played: PlayedIndex = new Map();
  for (const encounter of (encountersQuery.data?.results ?? []).filter(isEncounterCompleted)) {
    for (const match of encounter.matches ?? []) {
      for (const round of [String(encounter.round), "all"]) {
        const positions = match.map_index ? [0, match.map_index] : [0];
        for (const position of positions) {
          const key = `${encounter.stage_id}:${round}:${position}`;
          const counts = played.get(key) ?? new Map<number, number>();
          counts.set(match.map_id, (counts.get(match.map_id) ?? 0) + 1);
          played.set(key, counts);
        }
      }
    }
  }

  const stageParam = searchParams?.get("stage") ?? null;
  const selected = mapPool.stages.find((stage) => String(stage.stageId) === stageParam) ?? null;
  const pool = selected?.pool ?? mapPool.pool;
  const stages = selected ? [selected] : mapPool.stages;

  if (pool.total === 0) {
    return (
      <TournamentPageState
        state="empty"
        title={t("tournamentDetail.maps.emptyTitle")}
        description={t("tournamentDetail.maps.emptyDescription")}
      />
    );
  }

  return (
    <section
      className="grid w-full min-w-0 max-w-full gap-4 *:min-w-0"
      aria-label={t("common.maps")}
    >
      {mapPool.stages.length > 1 ? (
        <SectionToolbar label={t("tournamentDetail.mapPool.stagesLabel")}>
          <FilterChip
            active={selected === null}
            count={mapPool.pool.total}
            onClick={() => setParams({ stage: null })}
          >
            {t("tournamentDetail.mapPool.allStages")}
          </FilterChip>
          {mapPool.stages.map((stage) => (
            <FilterChip
              key={stage.stageId}
              active={selected?.stageId === stage.stageId}
              count={stage.pool.total}
              onClick={() => setParams({ stage: String(stage.stageId) })}
            >
              {stage.stageName}
            </FilterChip>
          ))}
        </SectionToolbar>
      ) : null}

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Eyebrow as="h2" className="aqt-tnum block">
          {t("tournamentDetail.mapPool.title", { count: pool.total })}
        </Eyebrow>
        <p className="text-caption text-[color:var(--aqt-fg-faint)]">
          {played.size > 0 ? tp("maps.playedLede") : t("tournamentDetail.mapPool.rounds.lede")}
        </p>
      </div>

      {stages.length === 0 ? (
        // One tournament-wide config: the merged pool IS the rule, by mode.
        <div className="grid gap-5">
          {pool.byGamemode.map((group) => (
            <div key={group.gamemode}>
              <Eyebrow as="h3" className="mb-2 flex items-center gap-1.5">
                <ModeIcon mode={group.maps[0]?.parent ?? null} />
                {group.gamemode}
              </Eyebrow>
              <div
                className="grid gap-2"
                style={{ gridTemplateColumns: "repeat(auto-fill, minmax(11rem, 1fr))" }}
              >
                {group.maps.map((map) => (
                  <MapCard key={map.id} map={map} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        stages.map((stage) => {
          // A round's height is its slots: split so both columns hold about as many.
          const { left, right, tail } = balanceColumns(
            stage.rounds,
            (round) => (round.slots?.length ?? 1) + 0.6
          );
          const card = (round: MapPoolScopeView) => (
            <RoundCard key={round.key} round={round} played={played} />
          );
          return (
            <section key={stage.stageId} aria-label={stage.stageName} className="grid gap-3">
              <h3 className="text-ui font-semibold text-[color:var(--aqt-fg)]">
                {stage.stageName}
              </h3>
              {left.length === 0 || right.length === 0 ? (
                <div className="grid gap-3">{stage.rounds.map(card)}</div>
              ) : (
                <>
                  <CardColumns even main={left.map(card)} side={right.map(card)} />
                  {tail ? <RoundCard round={tail} played={played} wide /> : null}
                </>
              )}
            </section>
          );
        })
      )}
    </section>
  );
}

/** The one mode every map here plays, or `null` when they disagree. */
function singleMode(maps: readonly CatalogEntityRead[]): CatalogEntityRead | null {
  const first = maps[0]?.parent ?? null;
  return first && maps.every((map) => map.parent?.id === first.id) ? first : null;
}

function ModeIcon({ mode }: Readonly<{ mode: CatalogEntityRead | null }>) {
  if (!mode?.image_path) return null;
  return (
    <Image src={mode.image_path} alt="" width={13} height={13} aria-hidden className="shrink-0" />
  );
}

/** A round: one row per map of the series, its mode named beside the number, the candidates three abreast. */
function RoundCard({
  round,
  played,
  wide = false
}: Readonly<{ round: MapPoolScopeView; played: PlayedIndex; wide?: boolean }>) {
  const t = useTranslations();
  const tp = useTranslations("tournamentDetail");
  // `round:<stageId>:<round>` or `stage:<stageId>` (a config for the whole stage).
  const [, stageId, roundNumber] = round.key.split(":");
  const scope = `${stageId}:${roundNumber ?? "all"}`;
  const slots = round.slots ?? [
    { position: 0, maps: round.pool.byGamemode.flatMap((group) => group.maps) }
  ];

  return (
    <TournamentTeamCardFrame
      data-map-pool-round={round.key}
      name={round.round ?? t("tournamentDetail.mapPool.rounds.wholeStage")}
      metricValue={round.slots ? `Bo${round.slots.length}` : undefined}
    >
      {/* Full width (the round left over under the columns), the series' maps sit side by side. */}
      <div
        className={cn(
          "divide-y divide-[color:var(--aqt-overlay-border)]",
          wide && "lg:grid lg:grid-cols-2 lg:divide-y-0"
        )}
      >
        {slots.map((slot) => {
          const mode = singleMode(slot.maps);
          const counts = played.get(`${scope}:${slot.position}`);
          return (
            <div
              key={slot.position}
              className="grid gap-2 px-3.5 py-3 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center sm:gap-3"
            >
              <div className="flex items-baseline gap-2 sm:grid sm:gap-0.5">
                {slot.position > 0 ? (
                  <Eyebrow as="div">
                    {t("tournamentDetail.mapPool.slot", { n: slot.position })}
                  </Eyebrow>
                ) : null}
                <span className="flex min-w-0 items-center gap-1.5 text-label text-[color:var(--aqt-fg-muted)]">
                  <ModeIcon mode={mode} />
                  <span className="truncate">{mode?.name ?? tp("maps.mixedModes")}</span>
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {slot.maps.map((map) => (
                  <MapStrip
                    key={map.id}
                    map={map}
                    times={counts ? (counts.get(map.id) ?? 0) : null}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </TournamentTeamCardFrame>
  );
}

/**
 * A candidate as a short strip — the picture, the name on a scrim. `times`: how often it was played in this slot,
 * `null` while the round has not been played; a candidate that never came up then steps back.
 */
function MapStrip({ map, times }: Readonly<{ map: CatalogEntityRead; times: number | null }>) {
  const tp = useTranslations("tournamentDetail");
  return (
    <figure
      title={map.name}
      className={cn(
        "relative aspect-[2/1] overflow-hidden rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] sm:aspect-[3/1]",
        times === 0 && "opacity-40"
      )}
    >
      {map.image_path ? (
        <Image src={map.image_path} alt="" fill sizes="180px" className="object-cover" />
      ) : (
        <span className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
          <ImageOff aria-hidden width={14} height={14} />
        </span>
      )}
      <span
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(to top, color-mix(in srgb, #000 80%, transparent), transparent 70%)"
        }}
      />
      {times ? (
        <span className="aqt-tnum absolute right-1 top-1 rounded bg-black/65 px-1.5 text-label font-semibold text-[color:var(--aqt-teal)]">
          ×{times}
        </span>
      ) : null}
      <figcaption className="absolute inset-x-0 bottom-0 truncate px-2 pb-1 text-label font-semibold text-white">
        {map.name}
        {times != null ? (
          <span className="sr-only">{tp("maps.playedTimes", { count: times })}</span>
        ) : null}
      </figcaption>
    </figure>
  );
}
