import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

export type TournamentSectionId =
  "bracket" | "teams" | "participants" | "matches" | "heroes" | "standings" | "draft";

export type TournamentNavReasonKey =
  "tournamentDetail.nav.reasons.competitionNotStarted" | "tournamentDetail.nav.reasons.noStages";

export type TournamentSectionNavItem = {
  id: TournamentSectionId;
  labelKey: `common.${TournamentSectionId}`;
  href: string;
  active: boolean;
  available: boolean;
  reasonKey: TournamentNavReasonKey | null;
};

type BuildTournamentSectionNavInput = {
  tournamentId: string;
  status: TournamentStatus;
  stages: StageSummary[];
  teamFormation?: string;
  pathname: string;
};

const competitionStatuses = new Set<TournamentStatus>([
  "live",
  "playoffs",
  "completed",
  "archived"
]);

const competitionOnlySections = new Set<TournamentSectionId>([
  "bracket",
  "teams",
  "matches",
  "heroes",
  "standings"
]);

const tournamentSections: Exclude<TournamentSectionId, "draft">[] = [
  "bracket",
  "teams",
  "participants",
  "matches",
  "heroes",
  "standings"
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

export function buildTournamentSectionNav({
  tournamentId,
  status,
  stages,
  teamFormation,
  pathname
}: BuildTournamentSectionNavInput): TournamentSectionNavItem[] {
  const competitionStarted = competitionStatuses.has(status);
  const currentPath = normalizePathname(pathname);
  const sections: TournamentSectionId[] =
    teamFormation === "draft" ? [...tournamentSections, "draft"] : tournamentSections;

  return sections.map((id) => {
    const href =
      id === "draft"
        ? `/draft/${tournamentId}`
        : id === "bracket"
          ? resolveBracketHref(tournamentId, stages)
          : `/tournaments/${tournamentId}/${id}`;
    const canonicalPath = href.split("?", 1)[0];
    const phaseLocked = competitionOnlySections.has(id) && !competitionStarted;
    const stageLocked = id === "bracket" && competitionStarted && stages.length === 0;

    return {
      id,
      labelKey: `common.${id}`,
      href,
      active: currentPath === canonicalPath,
      available: !phaseLocked && !stageLocked,
      reasonKey: phaseLocked
        ? "tournamentDetail.nav.reasons.competitionNotStarted"
        : stageLocked
          ? "tournamentDetail.nav.reasons.noStages"
          : null
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

export type TournamentRailMeasurementContainer = {
  readonly clientWidth: number;
};

type RailResizeObserver = {
  observe(target: TournamentRailElement | TournamentRailMeasurementContainer): void;
  disconnect(): void;
};

type WindowResizeTarget = {
  addEventListener(type: "resize", listener: () => void): void;
  removeEventListener(type: "resize", listener: () => void): void;
};

type ObserveTournamentRailOptions = {
  createResizeObserver?: ((callback: () => void) => RailResizeObserver) | null;
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
      ? typeof ResizeObserver === "undefined"
        ? null
        : (callback: () => void): RailResizeObserver => {
            const observer = new ResizeObserver(callback);
            return {
              observe(target) {
                observer.observe(target as Element);
              },
              disconnect() {
                observer.disconnect();
              }
            };
          }
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
