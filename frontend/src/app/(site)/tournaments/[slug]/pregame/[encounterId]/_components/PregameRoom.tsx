"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Clock, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { normalizeRole } from "@/lib/player-role";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { RETURN_TO_PARAM, safeReturnPath } from "@/lib/return-to";
import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import heroService from "@/services/hero.service";
import mapService from "@/services/map.service";
import pickBanService, { type PickBanActionInput } from "@/services/pickBan.service";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanAction, PickBanKind, PickBanState } from "@/types/tournament.types";

import {
  PICK_BAN_UNAVAILABLE_COPY,
  agreedMapScore,
  attributeLocks,
  highestPoolRound,
  isSessionActive,
  pickBanReserveMap,
  pickedItemsInOrder,
  seriesMatchesByPosition,
  type PickBanSide,
  type PickBanUnavailableIcon
} from "@/components/pick-ban/pick-ban-model";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanStepTimeline } from "@/components/pick-ban/PickBanStepTimeline";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";
import { PregameAdminControls } from "./PregameAdminControls";
import type { PregameHeroAction, PregameHeroRound } from "./PregameHeroBans";
import {
  PregameHeader,
  type PregamePhase,
  type PregamePhaseStatus,
  type PregameSeriesMap
} from "./PregameHeader";
import { PregameFinalReport } from "./PregameFinalReport";
import { PregameMapResult } from "./PregameMapResult";
import { PregameReadiness } from "./PregameReadiness";

interface PregameRoomProps {
  encounterId: number;
  /**
   * Whether the loop ends in the SERIES report (match codes, closeness, the
   * organizer's custom fields). False for a scrim room: it has no result to
   * publish and no organizer to read one, and the report form is built from a
   * per-tournament config a scrim container does not have. The per-map score is
   * unaffected — that one drives the progression, not the bookkeeping
   * (docs/plans/2026-08-12-scrim-rooms.md).
   */
  seriesReport?: boolean;
}

/** One icon per cause, keyed by what `PICK_BAN_UNAVAILABLE_COPY` names. */
const UNAVAILABLE_ICON: Record<PickBanUnavailableIcon, React.ReactNode> = {
  teams: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-teal)]" aria-hidden />,
  unconfigured: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />,
  misconfigured: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />,
  preview: <Clock className="h-6 w-6 text-[color:var(--aqt-fg-muted)]" aria-hidden />
};

/**
 * Unified pre-game room: one screen for the whole pre-game loop, which runs
 * once per map of the series —
 *
 *   map veto (this round's map) -> hero bans (for that map) -> the map is
 *   played and both captains report it -> that result opens the next map
 *
 * — until the series is decided. Both pick-ban kinds run on the same generic
 * `PickBanSession` engine, so one room renders either with the same
 * `PickBanGrid`/`PickBanStepTimeline`, and the backend keeps the loop honest:
 * a map round is only appended once the previous map's result is confirmed
 * (`pick_ban_session.advance_to_next_round`), and a hero round only once its
 * map is picked (`pick_ban_session.sync_hero_rounds`).
 *
 * Gated by `EncounterReadiness`: neither kind's session is created (backend:
 * `pick_ban_session.ensure_pick_ban_session`) until both captains confirm
 * readiness, shown here as a waiting screen with an "I'm ready" button.
 */
export function PregameRoom({ encounterId, seriesReport = true }: Readonly<PregameRoomProps>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const { isSuperuser, isWorkspaceAdmin, hasWorkspacePermission } = usePermissions();
  const enabled = Number.isFinite(encounterId) && encounterId > 0;
  const [freeplayMapId, setFreeplayMapId] = useState<number | null>(null);
  const searchParams = useSearchParams();
  const returnTo = safeReturnPath(searchParams?.get(RETURN_TO_PARAM), `/encounters/${encounterId}`);
  const mapKey = ["pregame-state", encounterId, "map"];
  const heroKey = ["pregame-state", encounterId, "hero"];
  // Turn timeouts auto-resolve lazily server-side, the next time anyone
  // reads this session's state (backend: `pick_ban_action.auto_resolve_timeout`)
  // -- there's no push event for time simply elapsing on its own, so an
  // active, unresolved session polls itself close to real time instead of
  // waiting for the next manual action or page load to notice the clock
  // ran out.
  const mapQuery = useQuery({
    queryKey: mapKey,
    queryFn: () => pickBanService.getPickBanState("map", encounterId),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.session != null && !query.state.data.is_complete ? 4000 : false
  });
  const heroQuery = useQuery({
    queryKey: heroKey,
    queryFn: () => pickBanService.getPickBanState("hero", encounterId),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.session != null && !query.state.data.is_complete ? 4000 : false
  });
  const encounterQuery = useQuery({
    queryKey: ["encounter-detail", encounterId],
    queryFn: () => encounterService.getEncounter(encounterId),
    enabled
  });
  const mapsQuery = useQuery({
    queryKey: ["maps-all"],
    queryFn: () => mapService.getAll({ perPage: -1 }),
    staleTime: 5 * 60 * 1000
  });
  const heroesQuery = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    staleTime: 5 * 60 * 1000
  });
  // `build_unavailable_state` reports `viewer_side: null` regardless of
  // identity (there is no session yet to resolve a side against), so the
  // readiness gate's "you're a captain" check needs its own read.
  const roleQuery = useQuery({
    queryKey: ["encounter", encounterId, "my-role"],
    queryFn: () => captainService.getMyRole(encounterId),
    enabled,
    retry: false
  });

  // The hub only delivers a thin "changed" signal on every mutation — the
  // authoritative state is always refetched. Map keeps the legacy topic name
  // (`encounter:{id}:map-veto`); hero uses the generic kind-suffixed one.
  // Either signal refetches BOTH: the two sessions are two phases of one loop,
  // so a map pick opens a hero round and a confirmed result opens a map round
  // — the state that changed is rarely only the one that was acted on.
  // The series score lives on the ENCOUNTER (`map_report.submit_map_report`
  // increments it), so a confirmed map moves a number this room renders from a
  // third query -- refetch it here too, or the captain who reported FIRST kept
  // reading a stale scoreboard until they reloaded.
  const invalidateRoom = () => {
    void queryClient.invalidateQueries({ queryKey: mapKey });
    void queryClient.invalidateQueries({ queryKey: heroKey });
    void queryClient.invalidateQueries({ queryKey: ["encounter-detail", encounterId] });
  };
  useRealtimeTopic(`encounter:${encounterId}:map-veto`, invalidateRoom);
  useRealtimeTopic(`encounter:${encounterId}:pick-ban:hero`, invalidateRoom);

  const readyMutation = useMutation({
    mutationFn: () => pickBanService.markReady(encounterId),
    onError: (error) => notify.apiError(error, { title: t("ready.failed") }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: mapKey });
      void queryClient.invalidateQueries({ queryKey: heroKey });
    }
  });

  const mapsById = useMemo(() => {
    const byId: Record<number, PickBanItemLike | undefined> = {};
    for (const map of mapsQuery.data?.results ?? []) byId[map.id] = map;
    return byId;
  }, [mapsQuery.data]);
  const heroesById = useMemo(() => {
    const byId: Record<number, PickBanItemLike | undefined> = {};
    for (const hero of heroesQuery.data?.results ?? []) byId[hero.id] = hero;
    return byId;
  }, [heroesQuery.data]);
  const itemsByKind: Record<PickBanKind, Record<number, PickBanItemLike | undefined>> = {
    map: mapsById,
    hero: heroesById
  };

  if (mapQuery.isPending || heroQuery.isPending || encounterQuery.isPending) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
        <Skeleton className="h-72 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  const encounter = encounterQuery.data ?? null;
  const mapState = mapQuery.data ?? null;
  const heroState = heroQuery.data ?? null;

  if (
    mapQuery.isError ||
    heroQuery.isError ||
    encounter === null ||
    mapState === null ||
    heroState === null
  ) {
    return (
      <EmptyRoomCard
        icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />}
        title={t("loadError")}
        action={
          <Button
            onClick={() => {
              void mapQuery.refetch();
              void heroQuery.refetch();
              void encounterQuery.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
        returnTo={returnTo}
      />
    );
  }

  const statesByKind: Record<PickBanKind, PickBanState> = { map: mapState, hero: heroState };
  // "Applicable" = something WOULD open here once teams/rules/readiness allow
  // it — everything except "there is genuinely no rule set for this kind".
  const applicable = (kind: PickBanKind) =>
    statesByKind[kind].reason !== "not_configured" || statesByKind[kind].session != null;
  const mapApplies = applicable("map");
  const heroApplies = applicable("hero");

  if (!mapApplies && !heroApplies) {
    return (
      <EmptyRoomCard
        icon={UNAVAILABLE_ICON.unconfigured}
        title={t("notConfiguredTitle")}
        hint={t("notConfiguredHint")}
        returnTo={returnTo}
      />
    );
  }

  const workspaceId = encounter.tournament?.workspace_id ?? null;
  const isAdmin =
    workspaceId != null &&
    (isSuperuser ||
      isWorkspaceAdmin(workspaceId) ||
      hasWorkspacePermission(workspaceId, "match.update"));
  const viewerSide = roleQuery.data?.side ?? null;

  // Readiness blocks EVERY kind's session at once (one gate per encounter) --
  // any applicable kind reporting "not_ready" means the room as a whole is
  // waiting on captains, never a per-kind state.
  const readiness = mapState.readiness;
  const waitingOnReadiness =
    !(readiness.home && readiness.away) &&
    (["map", "hero"] as PickBanKind[]).some(
      (kind) => applicable(kind) && statesByKind[kind].reason === "not_ready"
    );

  // ── where the loop stands ────────────────────────────────────────────────
  //
  // The maps this series has settled so far, in play order: index + 1 is the
  // round. The FIRST one still merely `picked` (not `played`) is the map whose
  // result the loop is waiting on -- `map_report.submit_map_report` flips it to
  // `played` the moment both captains agree, and that is what opens the next
  // map's bans.
  const seriesMaps = pickedItemsInOrder(mapState.pool);
  const pendingIndex = seriesMaps.findIndex((entry) => entry.status === "picked");
  const pendingMap = pendingIndex === -1 ? null : seriesMaps[pendingIndex];
  const pendingRound = pendingIndex === -1 ? null : pendingIndex + 1;
  const mapPhaseOpen = mapApplies && !(mapState.session != null && mapState.is_complete);
  // A hero round counts as settled only when it is the round of the map now
  // awaiting its result: a stale `is_complete` from the PREVIOUS round would
  // otherwise skip this map's bans in the window between its pick and the
  // server appending the round (`pick_ban_session.sync_hero_rounds`, on the
  // next read). With no map phase at all there is no round to align with, so
  // plain completeness is the whole answer.
  const heroRound = highestPoolRound(heroState.pool);
  const heroPhaseOpen =
    heroApplies &&
    !(
      heroState.session != null &&
      heroState.is_complete &&
      (pendingRound == null || (heroRound ?? 0) >= pendingRound)
    );

  // No map veto: after hero bans the captains name the map they played and
  // report its score. That agreed report is the barrier that opens the next
  // hero round.
  const winsNeeded = Math.floor((encounter.best_of ?? 0) / 2) + 1;
  const seriesDecided =
    (encounter.best_of ?? 0) > 0 &&
    Math.max(encounter.score?.home ?? 0, encounter.score?.away ?? 0) >= winsNeeded;
  const freeplayRound = !mapApplies ? (heroRound ?? 1) : null;
  const awaitingFreeplayReport =
    !mapApplies &&
    !heroPhaseOpen &&
    !seriesDecided &&
    (heroRound ?? 0) > 0 &&
    (heroRound ?? 0) <= (encounter.best_of ?? 0);
  const phase: PregamePhase = mapPhaseOpen
    ? "map"
    : heroPhaseOpen
      ? "hero"
      : pendingMap != null || awaitingFreeplayReport
        ? "report"
        : "done";
  // Which map of the series the room is on. During the map phase that is the
  // round being vetoed (one past the settled ones); afterwards it is the round
  // whose map is waiting to be played.
  const round = pendingRound ?? freeplayRound ?? (mapApplies ? seriesMaps.length + 1 : null);
  const phases: PregamePhaseStatus[] = [
    ...(mapApplies ? [{ phase: "map" as const, done: !mapPhaseOpen }] : []),
    ...(heroApplies ? [{ phase: "hero" as const, done: !heroPhaseOpen }] : []),
    ...(mapApplies || awaitingFreeplayReport || phase === "report"
      ? [{ phase: "report" as const, done: phase === "done" }]
      : [])
  ];
  // The series' history for the header filmstrip. Three distinct states, and
  // the pool is what tells them apart -- NOT the presence of a `Match` row:
  // a row exists for a map that a log parser touched or that was pre-created
  // at 0:0, so keying "settled" off `match != null` marked an unplayed map of
  // the series as finished and printed a 0:0 nobody scored.
  //
  // A `played` entry is settled and shows its confirmed score. Of the rest,
  // the FIRST one is the map the loop is waiting on right now (see
  // `pendingIndex`); every later one is simply a map of the series that has
  // not been reached yet and has no result to show at all.
  //
  // Which `Match` row belongs to which map of the series is `map_index`, never
  // `map_id`: a series may play the same map twice, and matching on the map
  // alone printed the first play's score on both.
  const seriesMatches = seriesMatchesByPosition(
    encounter.matches ?? [],
    seriesMaps.map((entry) => entry.item_id)
  );
  const series: PregameSeriesMap[] = seriesMaps.map((entry, index) => {
    const played = entry.status === "played";
    const match = played ? seriesMatches[index] : null;
    // A `Match` row is authoritative where one exists — a parsed log corrects a
    // captain claim. Where none does, the captains' own agreed claims are the
    // score: a scrim writes no match rows at all, and without this fallback its
    // played maps showed as played with nothing on them.
    const score =
      match != null
        ? { home: match.score.home, away: match.score.away }
        : played
          ? agreedMapScore(mapState.map_reports ?? [], index + 1)
          : null;
    return {
      round: index + 1,
      name: mapsById[entry.item_id]?.name ?? t("map.itemNumber", { id: entry.item_id }),
      item: mapsById[entry.item_id],
      score,
      state: played ? "played" : index === pendingIndex ? "awaiting" : "upcoming"
    };
  });
  // The hero bans that apply to one map of the series, resolved against the
  // catalog. The room shows one phase at a time, so once the hero grid closes
  // nothing on screen names what was banned -- which is precisely when the
  // captains have to enter it into the game lobby. A flat (round-less) hero
  // pool has one set of bans for the whole series, so it applies to every map.
  const heroActionsFor = (round: number | null): PregameHeroAction[] =>
    heroState.pool
      .filter(
        (entry) =>
          (round == null ? entry.round == null : entry.round == null || entry.round === round) &&
          (entry.status === "banned" || entry.status === "protected")
      )
      .map((entry) => {
        const item = heroesById[entry.item_id];
        const side = entry.status === "banned" ? entry.picked_by : entry.protected_by;
        return {
          itemId: entry.item_id,
          name: item?.name ?? t("hero.itemNumber", { id: entry.item_id }),
          item,
          role: normalizeRole(item?.type ?? item?.role),
          action: entry.status === "banned" ? ("ban" as const) : ("protect" as const),
          // `picked_by` also carries `"decider"`, which no ban can be.
          side: side === "away" ? ("away" as const) : ("home" as const)
        };
      });
  /** This map's bans, for the result screen. */
  const reportRound = pendingRound ?? freeplayRound;
  const heroActions: PregameHeroAction[] =
    reportRound == null ? [] : heroActionsFor(reportRound);
  // The whole series' bans, for the closing screen: by then no map is pending,
  // so `heroActions` is empty and the record of what each map was played under
  // would leave the room with the last grid that closed. Round-scoped pools get
  // one block per map; a flat pool has a single set that covered every map, so
  // repeating it per map would invent per-map decisions nobody made.
  const heroRounds: PregameHeroRound[] = (
    heroState.pool.some((entry) => entry.round != null)
      ? series.map((map) => ({
          round: map.round,
          mapName: map.name,
          mapItem: map.item,
          actions: heroActionsFor(map.round)
        }))
      : [{ round: null, mapName: null, mapItem: undefined, actions: heroActionsFor(null) }]
  ).filter((block) => block.actions.length > 0);
  const sideNameOf = (side: PickBanSide) =>
    side === "home"
      ? (encounter.home_team?.name ?? t("side.home"))
      : (encounter.away_team?.name ?? t("side.away"));
  const header = (
    <PregameHeader
      encounter={encounter}
      session={statesByKind[phase === "hero" || !mapApplies ? "hero" : "map"].session}
      activePhase={phase}
      phases={phases}
      round={round}
      series={series}
      returnTo={returnTo}
    />
  );

  if (waitingOnReadiness) {
    // One real card, header and all — no skeleton column beside it. Neither
    // session exists yet, so there is no pool and no step sequence to render,
    // and a shimmer that can only resolve when a human clicks "I'm ready" in
    // another browser reads as a page stuck loading.
    return (
      <Card>
        <CardContent className="flex flex-col gap-5 p-5">
          {header}
          <PregameReadiness
            encounter={encounter}
            readiness={readiness}
            viewerSide={viewerSide}
            pending={readyMutation.isPending}
            onReady={() => readyMutation.mutate()}
          />
        </CardContent>
      </Card>
    );
  }

  if (phase === "report" && reportRound != null) {
    const lockedMapId = pendingMap?.item_id ??
      (mapState.map_reports ?? []).find((report) => report.map_index === reportRound)?.map_id ??
      null;
    const reportMapId = lockedMapId ?? freeplayMapId;
    const reportMap = reportMapId != null ? mapsById[reportMapId] : undefined;
    return (
      <div className="flex flex-col gap-4">
        <PregameMapResult
          encounterId={encounterId}
          mapId={reportMapId}
          mapName={
            reportMap?.name ??
            (reportMapId != null ? t("map.itemNumber", { id: reportMapId }) : t("mapResult.pickMap"))
          }
          mapImagePath={reportMap?.image_path ?? null}
          round={reportRound}
          viewerSide={mapState.viewer_side ?? viewerSide}
          homeName={sideNameOf("home")}
          awayName={sideNameOf("away")}
          homeTeam={encounter.home_team ?? null}
          awayTeam={encounter.away_team ?? null}
          reports={(mapState.map_reports ?? []).filter((report) =>
            pendingMap != null
              ? report.map_id === pendingMap.item_id && report.map_index === reportRound
              : report.map_index === reportRound
          )}
          heroActions={heroActions}
          heroUndo={
            <PickBanUndoControl
              kind="hero"
              encounterId={encounterId}
              undo={heroState.undo}
              viewerSide={heroState.viewer_side}
              itemsById={heroesById}
              sideName={sideNameOf}
              invalidateKeys={[mapKey, heroKey]}
            />
          }
          header={header}
          invalidateKeys={[mapKey, heroKey, ["encounter-detail", encounterId]]}
          mapChoices={
            pendingMap == null
              ? (mapsQuery.data?.results ?? []).map((map) => ({ id: map.id, name: map.name }))
              : undefined
          }
          onSelectMap={pendingMap == null ? setFreeplayMapId : undefined}
        />
      </div>
    );
  }

  if (phase === "done") {
    // Without a report to file, the closing screen still owes the captains the
    // one thing they came for: who won. Read off the encounter's own series
    // score, which `submit_map_report` advances map by map — no extra request,
    // and it is the same number the header's filmstrip adds up.
    const home = encounter.score?.home ?? 0;
    const away = encounter.score?.away ?? 0;
    const outcome =
      home === away
        ? t("seriesDone.drawn", { home, away })
        : t("seriesDone.won", {
            team: sideNameOf(home > away ? "home" : "away"),
            home,
            away
          });
    return (
      <div className="flex flex-col gap-4">
        <PregameFinalReport
          encounter={encounter}
          viewerSide={mapState.viewer_side ?? viewerSide}
          reportable={seriesReport}
          outcome={outcome}
          heroRounds={heroRounds}
          homeName={sideNameOf("home")}
          awayName={sideNameOf("away")}
          header={header}
          returnTo={returnTo}
        />
      </div>
    );
  }

  const activeKind: PickBanKind = phase === "hero" ? "hero" : "map";
  const activeState = statesByKind[activeKind];

  if (activeState.session == null) {
    const copy = PICK_BAN_UNAVAILABLE_COPY[activeState.reason ?? "not_configured"];
    return (
      <EmptyRoomCard
        icon={UNAVAILABLE_ICON[copy.icon]}
        title={t(copy.titleKey)}
        hint={t(copy.hintKey)}
        returnTo={returnTo}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4 pb-32 sm:pb-28">
      <PickBanPanel
        key={activeKind}
        kind={activeKind}
        encounterId={encounterId}
        encounter={encounter}
        state={activeState}
        session={activeState.session}
        queryKey={activeKind === "map" ? mapKey : heroKey}
        itemsById={itemsByKind[activeKind]}
        isAdmin={isAdmin}
        header={header}
      />
    </div>
  );
}

function PickBanPanel({
  kind,
  encounterId,
  encounter,
  state,
  session,
  queryKey,
  itemsById,
  isAdmin,
  header
}: Readonly<{
  kind: PickBanKind;
  encounterId: number;
  encounter: Encounter;
  state: PickBanState;
  session: NonNullable<PickBanState["session"]>;
  queryKey: unknown[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  isAdmin: boolean;
  header: React.ReactNode;
}>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();

  const [pickedItemId, setSelectedItemId] = useState<number | null>(null);

  const selectedItemId =
    pickedItemId != null &&
    state.pool.some((entry) => entry.item_id === pickedItemId && entry.status === "available")
      ? pickedItemId
      : null;

  const actionMutation = useMutation({
    mutationFn: (input: PickBanActionInput) =>
      pickBanService.performPickBanAction(kind, encounterId, input),
    onSuccess: () => setSelectedItemId(null),
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  const sideName = (side: PickBanSide) =>
    side === "home"
      ? (encounter.home_team?.name ?? t("side.home"))
      : (encounter.away_team?.name ?? t("side.away"));

  const captainAction: PickBanAction | null =
    state.viewer_can_act && state.allowed_actions.length > 0 ? state.allowed_actions[0] : null;
  const canSelect =
    isSessionActive(session) && !state.is_complete && (captainAction !== null || isAdmin);
  const selectedItemName =
    selectedItemId != null
      ? (itemsById[selectedItemId]?.name ?? t(`${kind}.itemNumber`, { id: selectedItemId }))
      : null;
  const allowProtect = state.sequence.some((token) => token.startsWith("protect_"));

  // Read off the SIDE ON THE CLOCK, not the viewer: the rule constrains whoever
  // is acting, so a captain, their opponent and a spectator all see the same
  // greyed-out tiles instead of three different pools.
  const locks = attributeLocks({
    pool: state.pool,
    uniqueAttribute: state.unique_attribute,
    action: state.expected_action,
    side: state.turn_side,
    currentRound: state.current_round,
    attributeOf: (itemId) => normalizeRole(itemsById[itemId]?.type ?? itemsById[itemId]?.role)
  });
  // Same reading, from the ledger instead of the round: what the side on the
  // clock already banned earlier in this SERIES and may not ban again
  // (`no_repeat_scope=encounter_same_side`). Those items stay in the pool, so
  // without this the only feedback was the 400 after the click. Gated on a BAN
  // step because the ledger is ban memory only: a `protect` on an item this
  // side already banned is legal and meaningful — the OPPONENT is not barred
  // from banning it — so it must stay clickable.
  const repeatBanned = new Set(
    state.expected_action === "ban" ? (state.repeat_banned ?? []) : []
  );

  // The backend enforces who may elect (pending_loser_side); this only gates
  // whether the losing captain's own client shows the modal at all.
  const showElectOpener =
    session.awaiting_choice && state.viewer_side === session.pending_loser_side;
  // ...and everyone ELSE has to be told why the room stopped. The round the
  // choice is holding does not exist yet, so a spectator, the winning captain
  // and an organizer all saw a finished round with nothing to click and no
  // reason given — the exact shape of a hung room.
  const pendingOpenerSide = session.awaiting_choice ? session.pending_loser_side : null;

  return (
    <>
      {pendingOpenerSide != null ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-sm">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-[color:var(--aqt-fg-muted)]">
            {t("electOpener.waiting", { team: sideName(pendingOpenerSide) })}
          </p>
        </div>
      ) : null}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
        <PickBanStepTimeline
          kind={kind}
          sequence={state.sequence}
          pool={state.pool}
          currentStepIndex={state.current_step_index}
          isComplete={state.is_complete}
          currentRound={state.current_round}
          itemsById={itemsById}
          sideName={sideName}
          session={session}
        />
        <div className="flex flex-col gap-4">
          <PickBanGrid
            kind={kind}
            pool={state.pool}
            itemsById={itemsById}
            selectedItemId={selectedItemId}
            canSelect={canSelect}
            currentRound={state.current_round}
            slotReserves={pickBanReserveMap(session)}
            repeatBanned={repeatBanned}
            locks={locks}
            onSelect={(itemId) =>
              setSelectedItemId((current) => (current === itemId ? null : itemId))
            }
            header={header}
          />

          {/* Under the grid, above the admin panel: the correction path a
              captain reaches for belongs next to the pool they misclicked, and
              it is the captains' own — an organizer's blunt reset is separate. */}
          <PickBanUndoControl
            kind={kind}
            encounterId={encounterId}
            undo={state.undo}
            viewerSide={state.viewer_side}
            itemsById={itemsById}
            sideName={sideName}
            invalidateKeys={[queryKey]}
          />

          {isAdmin ? (
            <PregameAdminControls
              kind={kind}
              encounterId={encounterId}
              state={state}
              allowProtect={allowProtect}
              selectedItemId={selectedItemId}
              selectedItemName={selectedItemName}
              onMutated={() => {
                setSelectedItemId(null);
                void queryClient.invalidateQueries({ queryKey });
              }}
            />
          ) : null}
        </div>
      </div>

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          session={session}
          sideName={sideName}
          captainAction={state.is_complete ? null : captainAction}
          kind={kind}
          selectedItemId={selectedItemId}
          selectedItemName={selectedItemName}
          selectedItem={selectedItemId != null ? itemsById[selectedItemId] : undefined}
          pending={actionMutation.isPending}
          onConfirm={(itemId) => {
            if (captainAction != null)
              actionMutation.mutate({ item_id: itemId, action: captainAction });
          }}
          onCancel={() => setSelectedItemId(null)}
        />
      ) : null}

      <ElectOpenerDialog
        kind={kind}
        encounterId={encounterId}
        open={showElectOpener}
        homeName={sideName("home")}
        awayName={sideName("away")}
        queryKey={queryKey}
      />
    </>
  );
}

function EmptyRoomCard({
  icon,
  title,
  hint,
  action,
  returnTo
}: Readonly<{
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  returnTo: string;
}>) {
  const t = useTranslations("pickBan.room");

  return (
    <Card>
      <CardContent className="flex min-h-[40svh] flex-col items-center justify-center gap-3 p-8 text-center">
        {icon}
        <h1 className="font-onest text-xl font-semibold">{title}</h1>
        {hint ? (
          <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
            {hint}
          </p>
        ) : null}
        <div className="mt-2 flex items-center gap-2">
          {action}
          <Button variant="outline" asChild>
            <Link href={returnTo}>
              <ArrowLeft className="mr-2 h-4 w-4" aria-hidden />
              {t("back")}
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
