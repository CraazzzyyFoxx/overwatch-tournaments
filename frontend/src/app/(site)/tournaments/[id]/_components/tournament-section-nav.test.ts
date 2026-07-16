import { describe, expect, it } from "vitest";

import type { StageSummary, TournamentStatus } from "@/types/tournament.types";

import {
  buildTournamentSectionNav,
  getTournamentRailScrollState,
  observeTournamentRail,
  scrollTournamentRail,
  type TournamentRailElement
} from "./tournament-section-nav";

const tournamentId = "72";

function stage(overrides: Partial<StageSummary> = {}): StageSummary {
  return {
    id: 9,
    tournament_id: Number(tournamentId),
    name: "Playoffs",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 3,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_completed: false,
    settings_json: null,
    challonge_id: null,
    challonge_slug: null,
    ...overrides
  };
}

function model(
  status: TournamentStatus,
  pathname = `/tournaments/${tournamentId}/participants`,
  stages: StageSummary[] = [stage()]
) {
  return buildTournamentSectionNav({
    tournamentId,
    status,
    stages,
    teamFormation: "draft",
    pathname
  });
}

describe("buildTournamentSectionNav", () => {
  it.each<TournamentStatus>(["registration", "draft", "check_in"])(
    "keeps pre-competition data sections discoverable but locked during %s",
    (status) => {
      const items = model(status);
      const locked = items.filter((item) => !item.available);

      expect(locked.map((item) => item.id)).toEqual([
        "bracket",
        "teams",
        "matches",
        "heroes",
        "standings"
      ]);
      expect(items.find((item) => item.id === "participants")?.available).toBe(true);
      expect(items.find((item) => item.id === "draft")?.available).toBe(true);
      expect(locked.every((item) => Boolean(item.reasonKey))).toBe(true);
    }
  );

  it.each<TournamentStatus>(["live", "playoffs", "completed", "archived"])(
    "unlocks competition sections during %s when a stage exists",
    (status) => {
      expect(model(status).every((item) => item.available)).toBe(true);
    }
  );

  it("locks only the bracket for missing stage structure after competition starts", () => {
    const items = model("live", `/tournaments/${tournamentId}/bracket`, []);
    const bracket = items.find((item) => item.id === "bracket");

    expect(bracket).toMatchObject({
      available: false,
      active: true,
      reasonKey: "tournamentDetail.nav.reasons.noStages",
      href: `/tournaments/${tournamentId}/bracket`
    });
    expect(items.filter((item) => item.id !== "bracket").every((item) => item.available)).toBe(
      true
    );
  });

  it("prefers the active stage, then elimination, then group stage for the bracket href", () => {
    const stages = [
      stage({ id: 1, stage_type: "round_robin", is_active: false }),
      stage({ id: 2, stage_type: "double_elimination", is_active: false }),
      stage({ id: 3, stage_type: "swiss", is_active: true })
    ];

    expect(model("live", undefined, stages).find((item) => item.id === "bracket")?.href).toBe(
      `/tournaments/${tournamentId}/bracket?stage=3`
    );
  });

  it("uses stable ids and label keys and omits Draft for non-draft tournaments", () => {
    const items = buildTournamentSectionNav({
      tournamentId,
      status: "completed",
      stages: [stage()],
      teamFormation: "balancer",
      pathname: `/tournaments/${tournamentId}/teams`
    });

    expect(items.map(({ id, labelKey }) => [id, labelKey])).toEqual([
      ["bracket", "common.bracket"],
      ["teams", "common.teams"],
      ["participants", "common.participants"],
      ["matches", "common.matches"],
      ["heroes", "common.heroes"],
      ["standings", "common.standings"]
    ]);
  });

  it("links Draft to the standalone room and recognizes that route as active", () => {
    const draft = model("draft", `/draft/${tournamentId}`).find((item) => item.id === "draft");

    expect(draft).toMatchObject({
      href: `/draft/${tournamentId}`,
      active: true,
      available: true
    });
  });

  it("marks exactly the canonical nested route active", () => {
    const items = model("playoffs", `/tournaments/${tournamentId}/standings/`);

    expect(items.filter((item) => item.active).map((item) => item.id)).toEqual(["standings"]);
  });
});

class FakeRail implements TournamentRailElement {
  scrollWidth = 100;
  clientWidth = 100;
  scrollLeft = 0;
  private scrollListeners = new Set<() => void>();

  addEventListener(_type: "scroll", listener: () => void) {
    this.scrollListeners.add(listener);
  }

  removeEventListener(_type: "scroll", listener: () => void) {
    this.scrollListeners.delete(listener);
  }

  scrollBy(options: ScrollToOptions) {
    const maxScrollLeft = Math.max(0, this.scrollWidth - this.clientWidth);
    this.scrollLeft = Math.min(maxScrollLeft, Math.max(0, this.scrollLeft + (options.left ?? 0)));
    this.emitScroll();
  }

  emitScroll() {
    this.scrollListeners.forEach((listener) => listener());
  }

  get listenerCount() {
    return this.scrollListeners.size;
  }
}

function createFrameScheduler() {
  let nextId = 1;
  const frames = new Map<number, FrameRequestCallback>();
  const cancelled: number[] = [];

  return {
    requestAnimationFrame(callback: FrameRequestCallback) {
      const id = nextId++;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id: number) {
      cancelled.push(id);
      frames.delete(id);
    },
    flush() {
      const pending = [...frames.entries()];
      frames.clear();
      pending.forEach(([, callback]) => callback(0));
    },
    cancelled
  };
}

describe("tournament rail overflow behavior", () => {
  it("derives no-overflow, left-edge, middle, and right-edge controls with tolerance", () => {
    expect(
      getTournamentRailScrollState({ scrollWidth: 100, clientWidth: 100, scrollLeft: 0 })
    ).toEqual({ hasOverflow: false, canScrollPrevious: false, canScrollNext: false });
    expect(
      getTournamentRailScrollState({ scrollWidth: 300, clientWidth: 100, scrollLeft: 1 })
    ).toEqual({ hasOverflow: true, canScrollPrevious: false, canScrollNext: true });
    expect(
      getTournamentRailScrollState({ scrollWidth: 300, clientWidth: 100, scrollLeft: 80 })
    ).toEqual({ hasOverflow: true, canScrollPrevious: true, canScrollNext: true });
    expect(
      getTournamentRailScrollState({ scrollWidth: 300, clientWidth: 100, scrollLeft: 199 })
    ).toEqual({ hasOverflow: true, canScrollPrevious: true, canScrollNext: false });
  });

  it("updates edge controls after explicit next/previous scrolling", () => {
    const rail = new FakeRail();
    rail.scrollWidth = 300;
    const scheduler = createFrameScheduler();
    const states: ReturnType<typeof getTournamentRailScrollState>[] = [];
    const observer = observeTournamentRail(rail, (state) => states.push(state), {
      createResizeObserver: null,
      windowTarget: { addEventListener() {}, removeEventListener() {} },
      ...scheduler
    });
    scheduler.flush();

    scrollTournamentRail(rail, 1, "auto");
    scheduler.flush();
    expect(states.at(-1)).toEqual({
      hasOverflow: true,
      canScrollPrevious: true,
      canScrollNext: true
    });

    scrollTournamentRail(rail, 1, "auto");
    scheduler.flush();
    expect(states.at(-1)).toEqual({
      hasOverflow: true,
      canScrollPrevious: true,
      canScrollNext: false
    });

    scrollTournamentRail(rail, -1, "auto");
    scheduler.flush();
    expect(states.at(-1)?.canScrollNext).toBe(true);
    observer.cleanup();
  });

  it("remeasures through ResizeObserver and disconnects listeners and queued frames", () => {
    const rail = new FakeRail();
    const scheduler = createFrameScheduler();
    const states: ReturnType<typeof getTournamentRailScrollState>[] = [];
    let resizeCallback: (() => void) | undefined;
    let disconnected = false;

    const observer = observeTournamentRail(rail, (state) => states.push(state), {
      createResizeObserver(callback) {
        resizeCallback = callback;
        return {
          observe() {},
          disconnect() {
            disconnected = true;
          }
        };
      },
      ...scheduler
    });
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(false);
    expect(rail.listenerCount).toBe(1);

    rail.scrollWidth = 260;
    resizeCallback?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(true);

    rail.emitScroll();
    observer.cleanup();
    expect(disconnected).toBe(true);
    expect(rail.listenerCount).toBe(0);
    expect(scheduler.cancelled).toHaveLength(1);
  });

  it("uses and removes a window resize fallback when ResizeObserver is unavailable", () => {
    const rail = new FakeRail();
    const scheduler = createFrameScheduler();
    const states: ReturnType<typeof getTournamentRailScrollState>[] = [];
    let resizeListener: (() => void) | undefined;
    let removed = false;
    const observer = observeTournamentRail(rail, (state) => states.push(state), {
      createResizeObserver: null,
      windowTarget: {
        addEventListener(_type, listener) {
          resizeListener = listener;
        },
        removeEventListener(_type, listener) {
          removed = listener === resizeListener;
        }
      },
      ...scheduler
    });
    scheduler.flush();

    rail.scrollWidth = 220;
    resizeListener?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(true);
    observer.cleanup();

    expect(removed).toBe(true);
  });

  it("does not let reserved control columns create borderline overflow hysteresis", () => {
    const rail = new FakeRail();
    const container = { clientWidth: 520 };
    const contentWidth = 500;
    const scheduler = createFrameScheduler();
    const states: ReturnType<typeof getTournamentRailScrollState>[] = [];
    let resizeCallback: (() => void) | undefined;
    const applyLayout = (withControls: boolean) => {
      rail.clientWidth = container.clientWidth - (withControls ? 64 : 0);
      rail.scrollWidth = Math.max(contentWidth, rail.clientWidth);
    };

    applyLayout(false);
    const observer = observeTournamentRail(rail, (state) => states.push(state), {
      measurementContainer: container,
      createResizeObserver(callback) {
        resizeCallback = callback;
        return { observe() {}, disconnect() {} };
      },
      ...scheduler
    });
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(false);

    container.clientWidth = 450;
    applyLayout(false);
    resizeCallback?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(true);

    applyLayout(true);
    resizeCallback?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(true);

    container.clientWidth = 520;
    applyLayout(true);
    resizeCallback?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(false);

    applyLayout(false);
    resizeCallback?.();
    scheduler.flush();
    expect(states.at(-1)?.hasOverflow).toBe(false);
    observer.cleanup();
  });
});
