"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { FilterChip } from "@/components/ui/filter-chip";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import type { MapRead } from "@/types/map.types";

import styles from "../TournamentDetail.module.css";
import { MapCard } from "../_components/MapCard";
import { SectionToolbar } from "../_components/SectionToolbar";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentMapsSkeleton } from "../_components/TournamentSkeletons";
import { UpdatingBadge } from "../_components/UpdatingBadge";
import {
  useTournamentMapPool,
  type MapPoolScopeView,
  type MapPoolStageView
} from "../_hooks/useTournamentMapPool";
import { getPublicPageQueryPresentation } from "@/lib/public-page-query-presentation";

const EYEBROW =
  "aqt-tnum block text-label uppercase tracking-[0.06em] text-[color:var(--aqt-fg-faint)]";
const LABEL =
  "text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]";

type Gamemode = NonNullable<MapRead["gamemode"]>;

/** The one game mode every map here plays, or `null` when they disagree. */
function singleGamemode(maps: readonly MapRead[]): Gamemode | null {
  const first = maps[0]?.gamemode ?? null;
  if (first === null) return null;
  return maps.every((map) => map.gamemode?.id === first.id) ? first : null;
}

/** Every map of a pool-mode round, in mode order. */
function roundPoolMaps(round: MapPoolScopeView): MapRead[] {
  return round.pool.byGamemode.flatMap((group) => group.maps);
}

/** The mode's own glyph — an icon says "Control" faster than the word does. */
function ModeIcon({ gamemode }: Readonly<{ gamemode: Gamemode | null }>) {
  if (!gamemode?.image_path) return null;
  return (
    <Image
      src={gamemode.image_path}
      alt=""
      width={13}
      height={13}
      aria-hidden
      title={gamemode.name}
      className="shrink-0"
    />
  );
}

/**
 * The tournament's map pool — which maps it plays, and when each one can be
 * played, in pictures.
 *
 * Play counts live in Statistics: this section is the regulation a player reads
 * before the tournament starts, and Statistics is locked until it does.
 */
export default function TournamentMapsPage({
  tournamentId
}: Readonly<{ tournamentId: number; slug: string }>) {
  const t = useTranslations();
  const { searchParams, setParams } = useQueryParams();
  const mapPool = useTournamentMapPool(tournamentId);

  // `useTournamentMapPool` exposes no `data`, so "has something to show" is
  // derived: an errored first read leaves the pool empty, and passing that
  // along would claim the organizer published no maps. Stale content still
  // survives a failed refresh.
  const poolLoaded = !mapPool.isPending && !(mapPool.isError && mapPool.pool.total === 0);
  const presentation = getPublicPageQueryPresentation({
    data: poolLoaded ? mapPool.pool : undefined,
    itemCount: mapPool.pool.total,
    isPending: mapPool.isPending,
    isError: mapPool.isError,
    isFetching: mapPool.isFetching
  });

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => mapPool.refetch()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentMapsSkeleton />;
  }

  const stageParam = searchParams?.get("stage") ?? null;
  const selected =
    mapPool.stages.find((stage) => String(stage.stageId) === stageParam) ?? null;
  // Selecting a stage narrows both blocks: the pool becomes what that stage can
  // play, and only its rounds are laid out below.
  const pool = selected?.pool ?? mapPool.pool;
  const stages: MapPoolStageView[] = selected ? [selected] : mapPool.stages;

  const content = (
    <section className={styles.publicDataPage} aria-label={t("common.maps")}>
      {presentation.showUpdating ? <UpdatingBadge /> : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.maps.emptyTitle")}
          description={t("tournamentDetail.maps.emptyDescription")}
        />
      ) : (
        <>
          {/* One stage is no choice: the chips appear only where they filter. */}
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

          <div id="map-pool" className="scroll-mt-28 border-t border-[color:var(--aqt-border)] pt-3">
            <h2 className={cn(EYEBROW, "mb-1")}>
              {t("tournamentDetail.mapPool.title", { count: pool.total })}
            </h2>
            <p className="mb-3 text-caption text-[color:var(--aqt-fg-faint)]">
              {t("tournamentDetail.mapPool.rounds.lede")}
            </p>
            {/* The pool is only ever shown per round: a merged list of every map
                the tournament may touch answers no question a reader has, since
                no single match plays from it. The flat grid below is the
                fallback for the one case with no rounds to lay out — a single
                tournament-wide config, where the merged list IS the rule. */}
            {stages.length === 0 ? (
              <div className="grid gap-5">
                {pool.byGamemode.map((group) => (
                  <div key={group.gamemode}>
                    <h3 className={cn(LABEL, "mb-2 flex items-center gap-1.5")}>
                      {group.maps[0]?.gamemode?.image_path ? (
                        <Image
                          src={group.maps[0].gamemode.image_path}
                          alt=""
                          width={14}
                          height={14}
                          aria-hidden
                        />
                      ) : null}
                      {group.gamemode}
                      <span className="aqt-tnum text-[color:var(--aqt-fg-dim)]">
                        {group.maps.length}
                      </span>
                    </h3>
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
              <div className="grid gap-5">
                {stages.map((stage) => (
                  <section key={stage.stageId}>
                    <h3 className={cn(LABEL, "mb-2")}>{stage.stageName}</h3>
                    <div className="grid">
                      {stage.rounds.map((round) => {
                        const roundMode = singleGamemode(
                          round.pool.byGamemode.flatMap((group) => group.maps)
                        );
                        return (
                          <div
                            key={round.key}
                            data-map-pool-round={round.key}
                            className="grid grid-cols-1 gap-x-5 gap-y-2 border-t border-[color:var(--aqt-border)] py-3 sm:grid-cols-[minmax(5rem,7rem)_minmax(0,1fr)]"
                          >
                            <div className="flex items-baseline gap-2 sm:block">
                              <div className="flex items-center gap-1.5 text-caption font-semibold">
                                <ModeIcon gamemode={roundMode} />
                                {round.round ?? t("tournamentDetail.mapPool.rounds.wholeStage")}
                              </div>
                              {round.slots ? (
                                <div className={cn(LABEL, "aqt-tnum sm:mt-0.5")}>
                                  Bo{round.slots.length}
                                </div>
                              ) : null}
                            </div>
                            {/* One ROW per map of the series: the candidates for
                                map 1 read left to right, map 2 on the line
                                below. Stacking them into columns made a round
                                read top-to-bottom, against the order it plays. */}
                            <div className="grid gap-2">
                              {(round.slots ?? [{ position: 0, maps: roundPoolMaps(round) }]).map(
                                (slot) => {
                                  // A slot is usually one mode (three Control
                                  // maps); naming it once beats an icon on every
                                  // card. Skipped when the whole round already
                                  // carries that icon.
                                  const slotMode =
                                    roundMode === null ? singleGamemode(slot.maps) : null;
                                  return (
                                    <div
                                      key={slot.position}
                                      className="grid grid-cols-1 gap-1 sm:grid-cols-[minmax(4.5rem,6.5rem)_minmax(0,1fr)] sm:items-start sm:gap-3"
                                    >
                                      {slot.position > 0 ? (
                                        <div
                                          className={cn(LABEL, "flex items-center gap-1.5 sm:pt-1")}
                                        >
                                          <ModeIcon gamemode={slotMode} />
                                          {t("tournamentDetail.mapPool.slot", {
                                            n: slot.position
                                          })}
                                        </div>
                                      ) : (
                                        <span />
                                      )}
                                      <div className="flex flex-wrap gap-2">
                                        {slot.maps.map((map) => (
                                          <MapCard
                                            key={map.id}
                                            map={map}
                                            size="sm"
                                            className="w-[9rem]"
                                          />
                                        ))}
                                      </div>
                                    </div>
                                  );
                                }
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => mapPool.refetch()}
        isUpdating={presentation.showUpdating}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
}
