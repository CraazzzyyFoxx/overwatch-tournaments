import { reachedAtLeast } from "@/lib/tournament-lifecycle";
import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

export type TournamentSectionId =
  | "overview" | "rules" | "bracket" | "teams" | "matches" | "maps" | "stats" | "stream" | "participants";

type TournamentNavReasonKey =
  | "tournamentDetail.nav.reasons.competitionNotStarted"
  | "tournamentDetail.nav.reasons.noStages"
  | "tournamentDetail.nav.reasons.noTeams";

/** Every section labels itself from `common.<id>`. */
export type TournamentSectionLabelKey = `common.${TournamentSectionId}`;

export type TournamentSectionNavItem = {
  id: TournamentSectionId;
  labelKey: TournamentSectionLabelKey;
  href: string;
  active: boolean;
  available: boolean;
  reasonKey: TournamentNavReasonKey | null;
};

type BuildTournamentSectionNavInput = {
  tournamentId: string;
  status: TournamentStatus;
  stages: StageSummary[];
  /**
   * Whether any team exists yet. Teams are formed before play starts (balancer
   * run or draft), so the section opens as soon as there is a roster to show
   * rather than waiting for the competition phase.
   */
  hasTeams?: boolean;
  /**
   * Whether the tournament has any stream at all — an official broadcast link
   * or a participant currently live. Unlike Teams, the Stream section does not
   * lock when it is empty: it disappears. A lock advertises content the
   * organizer has not published YET, and every tournament would carry that
   * promise forever, because most of them never have a stream.
   */
  hasStreams?: boolean;
  /**
   * Whether the organizer published a rules document. Absent-or-present like
   * Stream and for the same reason: an empty Rules tab would promise a
   * regulation nobody wrote, and most tournaments publish none.
   */
  hasRules?: boolean;
  pathname: string;
};

const competitionOnlySections = new Set<TournamentSectionId>(["bracket", "matches", "stats"]);

/**
 * The rail's order is a function of the phase, not a constant. Before play the
 * viewer's job is to register and see who else did, so Participants sits second;
 * once play starts the registration list is history and moves to the end, behind
 * everything that describes the competition itself.
 */
const preCompetitionOrder: TournamentSectionId[] = [
  "overview",
  // The regulations sit directly under the overview in BOTH orders, and they
  // are the one section that does not move with the phase: before play they
  // are what a player reads to decide whether to sign up, during play they are
  // what a dispute is settled by. Neither is a thing to hunt for at the far end
  // of the rail.
  "rules",
  "participants",
  // Which maps the tournament plays is reference data a registering player
  // reads before anything about the bracket, so it sits ahead of it.
  "maps",
  "teams",
  "bracket",
  "matches",
  "stats"
];

const competitionOrder: TournamentSectionId[] = [
  "overview",
  "rules",
  "bracket",
  "teams",
  "matches",
  "maps",
  "stats",
  "stream",
  "participants"
];

function normalizePathname(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

function resolveBracketHref(tournamentId: string, stages: StageSummary[]): string {
  const active = stages.find((stage) => stage.is_active);
  const elimination = stages.find(
    (stage) =>
      stage.stage_type === "single_elimination" || stage.stage_type === "double_elimination"
  );
  const group = stages.find(
    (stage) => stage.stage_type === "round_robin" || stage.stage_type === "swiss"
  );
  const primary = active ?? elimination ?? group ?? stages[0];

  return primary
    ? `/tournaments/${tournamentId}/bracket?stage=${primary.id}`
    : `/tournaments/${tournamentId}/bracket`;
}

/**
 * Why a section is locked, or `null` when nothing locks it. Order is the
 * precedence the rail explains: the phase gate is the broadest reason, so it
 * speaks first, and the per-section gates only get a say once the phase allows
 * the section at all. `available` is the absence of any reason, so the tooltip
 * and the lock can never disagree.
 */
function resolveNavLockReason(
  locks: Readonly<{
    phaseLocked: boolean;
    stageLocked: boolean;
    teamsLocked: boolean;
  }>
): TournamentNavReasonKey | null {
  if (locks.phaseLocked) return "tournamentDetail.nav.reasons.competitionNotStarted";
  if (locks.stageLocked) return "tournamentDetail.nav.reasons.noStages";
  if (locks.teamsLocked) return "tournamentDetail.nav.reasons.noTeams";
  return null;
}

export function buildTournamentSectionNav({
  tournamentId,
  status,
  stages,
  hasTeams = false,
  hasStreams = false,
  hasRules = false,
  pathname
}: BuildTournamentSectionNavInput): TournamentSectionNavItem[] {
  const competitionStarted = reachedAtLeast(status, "live");
  const currentPath = normalizePathname(pathname);
  // `stream` and `rules` are present-or-absent rather than open-or-locked,
  // because a locked tab claims the content exists somewhere. Both are filtered
  // from their display position so the rail keeps one order in every case.
  const sections = (competitionStarted ? competitionOrder : preCompetitionOrder).filter(
    (id) => (id !== "stream" || hasStreams) && (id !== "rules" || hasRules)
  );

  return sections.map((id) => {
    const href =
      id === "overview"
        ? `/tournaments/${tournamentId}`
        : id === "bracket"
          ? resolveBracketHref(tournamentId, stages)
          : `/tournaments/${tournamentId}/${id}`;
    const canonicalPath = href.split("?", 1)[0];
    const phaseLocked = competitionOnlySections.has(id) && !competitionStarted;
    const stageLocked = id === "bracket" && competitionStarted && stages.length === 0;
    const teamsLocked = id === "teams" && !hasTeams && !competitionStarted;
    const reasonKey = resolveNavLockReason({ phaseLocked, stageLocked, teamsLocked });

    return {
      id,
      labelKey: `common.${id}`,
      href,
      active: currentPath === canonicalPath,
      available: reasonKey === null,
      reasonKey
    };
  });
}

export type TournamentRailElement = {
  readonly scrollWidth: number;
  readonly clientWidth: number;
  scrollLeft: number;
  addEventListener(type: "scroll", listener: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: "scroll", listener: () => void): void;
  scrollBy(options: ScrollToOptions): void;
};

export type TournamentRailScrollState = {
  hasOverflow: boolean;
  canScrollPrevious: boolean;
  canScrollNext: boolean;
};

type TournamentRailMeasurementContainer = {
  readonly clientWidth: number;
};

type RailResizeObserver = {
  observe(target: TournamentRailElement | TournamentRailMeasurementContainer): void;
  disconnect(): void;
};

type RailResizeObserverFactory = (callback: () => void) => RailResizeObserver;

type WindowResizeTarget = {
  addEventListener(type: "resize", listener: () => void): void;
  removeEventListener(type: "resize", listener: () => void): void;
};

type ObserveTournamentRailOptions = {
  createResizeObserver?: RailResizeObserverFactory | null;
  measurementContainer?: TournamentRailMeasurementContainer;
  windowTarget?: WindowResizeTarget;
  requestAnimationFrame?: (callback: FrameRequestCallback) => number;
  cancelAnimationFrame?: (id: number) => void;
};

const SCROLL_EDGE_TOLERANCE = 2;

export function getTournamentRailScrollState(
  rail: Pick<TournamentRailElement, "scrollWidth" | "clientWidth" | "scrollLeft">,
  availableWidth = rail.clientWidth
): TournamentRailScrollState {
  const maxScrollLeft = Math.max(0, rail.scrollWidth - rail.clientWidth);
  const hasOverflow = rail.scrollWidth - availableWidth > SCROLL_EDGE_TOLERANCE;

  return {
    hasOverflow,
    canScrollPrevious: hasOverflow && rail.scrollLeft > SCROLL_EDGE_TOLERANCE,
    canScrollNext: hasOverflow && maxScrollLeft - rail.scrollLeft > SCROLL_EDGE_TOLERANCE
  };
}

export function scrollTournamentRail(
  rail: TournamentRailElement,
  direction: -1 | 1,
  behavior: ScrollBehavior
) {
  rail.scrollBy({
    left: direction * Math.max(180, rail.clientWidth * 0.65),
    behavior
  });
}

/**
 * The platform `ResizeObserver`, adapted to `RailResizeObserver`; `null` where
 * the API is absent (SSR, older jsdom) and the rail has to fall back to window
 * resize events alone. Kept out of `observeTournamentRail` so that its option
 * plumbing stays a single flat choice: `undefined` means "use this default",
 * `null` means "observing is deliberately off".
 */
function defaultRailResizeObserverFactory(): RailResizeObserverFactory | null {
  if (typeof ResizeObserver === "undefined") return null;

  return (callback: () => void): RailResizeObserver => {
    const observer = new ResizeObserver(callback);
    return {
      observe(target) {
        observer.observe(target as Element);
      },
      disconnect() {
        observer.disconnect();
      }
    };
  };
}

export function observeTournamentRail(
  rail: TournamentRailElement,
  onChange: (state: TournamentRailScrollState) => void,
  options: ObserveTournamentRailOptions = {}
) {
  const requestFrame = options.requestAnimationFrame ?? window.requestAnimationFrame.bind(window);
  const cancelFrame = options.cancelAnimationFrame ?? window.cancelAnimationFrame.bind(window);
  const windowTarget = options.windowTarget ?? (typeof window === "undefined" ? null : window);
  const createResizeObserver =
    options.createResizeObserver === undefined
      ? defaultRailResizeObserverFactory()
      : options.createResizeObserver;
  let frameId: number | null = null;
  let disposed = false;

  const refresh = () => {
    if (disposed) return;
    if (frameId !== null) return;
    frameId = requestFrame(() => {
      frameId = null;
      if (!disposed) {
        onChange(
          getTournamentRailScrollState(
            rail,
            options.measurementContainer?.clientWidth ?? rail.clientWidth
          )
        );
      }
    });
  };

  rail.addEventListener("scroll", refresh, { passive: true });
  const resizeObserver = createResizeObserver?.(refresh) ?? null;
  if (resizeObserver) {
    resizeObserver.observe(rail);
    if (options.measurementContainer) {
      resizeObserver.observe(options.measurementContainer);
    }
  } else windowTarget?.addEventListener("resize", refresh);
  refresh();

  return {
    refresh,
    cleanup() {
      if (disposed) return;
      disposed = true;
      rail.removeEventListener("scroll", refresh);
      if (resizeObserver) resizeObserver.disconnect();
      else windowTarget?.removeEventListener("resize", refresh);
      if (frameId !== null) {
        cancelFrame(frameId);
        frameId = null;
      }
    }
  };
}
