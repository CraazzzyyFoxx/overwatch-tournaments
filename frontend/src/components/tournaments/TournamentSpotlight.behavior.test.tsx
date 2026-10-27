// @vitest-environment happy-dom
//
// Which tournament holds the spotlight's stage: the one a thumbnail picks, the
// next one once the interval runs out, the same one for as long as the pointer
// rests on it, and the same one from pause until play.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament } from "@/types/tournament.types";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch: _prefetch,
    ...rest
  }: {
    href: string;
    prefetch?: boolean;
    children: React.ReactNode;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));
// `fill`/`sizes`/`unoptimized` are Next-only props, not DOM attributes.
vi.mock("next/image", () => ({
  default: ({
    fill: _fill,
    sizes: _sizes,
    unoptimized: _unoptimized,
    ...props
  }: React.ImgHTMLAttributes<HTMLImageElement> & {
    fill?: boolean;
    sizes?: string;
    unoptimized?: boolean;
    // eslint-disable-next-line @next/next/no-img-element -- this IS the next/image stand-in
  }) => <img {...props} alt={props.alt ?? ""} />
}));

import { SPOTLIGHT_INTERVAL_MS, TournamentSpotlight } from "./TournamentSpotlight";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** Every field spelled out: test files are outside `tsconfig.json`, so a cast
 *  would type-check green over a fixture missing what the stage reads. */
function tournament(id: number, name: string): Tournament {
  return {
    id,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-02T00:00:00Z"),
    workspace_id: 1,
    name,
    slug: name.toLowerCase().replace(/\s+/g, "-"),
    start_date: new Date("2026-02-01T00:00:00Z"),
    end_date: new Date("2026-02-08T00:00:00Z"),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: true,
    is_hidden: false,
    team_formation: "balancer",
    status: "completed",
    auto_transitions_enabled: false,
    allow_late_registration: false,
    phase_schedule: [],
    win_points: 3,
    draw_points: 1,
    loss_points: 0,
    stages: [],
    participants_count: 30,
    registrations_count: null,
    teams_count: 6,
    division_grid_version_id: null,
    division_grid_version: null,
    discipline: "overwatch",
    roster_shape: null,
    roster_locked_by_draft: null,
    cover_image_url: null,
    logo_url: null
  };
}

const ITEMS = ["Spring Cup", "Summer Cup", "Autumn Cup"].map((name, index) => ({
  tournament: tournament(index + 1, name),
  picture: null
}));

let container: HTMLDivElement;
let root: Root;

/** The name on the stage (the thumbnails carry theirs as button names). */
const onStage = () => container.querySelector("b")?.textContent;

async function wait(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

beforeEach(async () => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <TournamentSpotlight items={ITEMS} />
      </NextIntlClientProvider>
    );
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("TournamentSpotlight", () => {
  it("shows the tournament whose thumbnail is clicked", async () => {
    const thumbnail = container.querySelector<HTMLButtonElement>('button[aria-label="Autumn Cup"]');

    await act(async () => thumbnail?.click());

    expect(onStage()).toBe("Autumn Cup");
    expect(thumbnail?.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector('button[aria-label="Spring Cup"]')?.getAttribute("aria-pressed")).toBe("false");
  });

  it("moves on to the next tournament by itself once the interval runs out", async () => {
    await wait(SPOTLIGHT_INTERVAL_MS - 1);
    expect(onStage()).toBe("Spring Cup");

    await wait(1);
    expect(onStage()).toBe("Summer Cup");
  });

  it("holds the stage while the pointer rests on it", async () => {
    // The stage itself; its parent group also holds the pause/play button.
    const stage = container.firstElementChild?.firstElementChild as HTMLElement;

    await act(async () => {
      stage.dispatchEvent(new PointerEvent("pointerover", { bubbles: true, pointerType: "mouse" }));
    });
    await wait(SPOTLIGHT_INTERVAL_MS * 3);
    expect(onStage()).toBe("Spring Cup");

    // Leaving starts a fresh interval rather than jumping at once.
    await act(async () => {
      stage.dispatchEvent(
        new PointerEvent("pointerout", { bubbles: true, pointerType: "mouse", relatedTarget: document.body })
      );
    });
    expect(onStage()).toBe("Spring Cup");
    await wait(SPOTLIGHT_INTERVAL_MS);
    expect(onStage()).toBe("Summer Cup");
  });

  it("stops moving on once paused, and moves on again once played", async () => {
    const { pause, play } = en.tournamentsList.spotlight;

    await act(async () => container.querySelector<HTMLButtonElement>(`button[aria-label="${pause}"]`)?.click());
    await wait(SPOTLIGHT_INTERVAL_MS * 3);
    expect(onStage()).toBe("Spring Cup");

    await act(async () => container.querySelector<HTMLButtonElement>(`button[aria-label="${play}"]`)?.click());
    await wait(SPOTLIGHT_INTERVAL_MS);
    expect(onStage()).toBe("Summer Cup");
  });
});
