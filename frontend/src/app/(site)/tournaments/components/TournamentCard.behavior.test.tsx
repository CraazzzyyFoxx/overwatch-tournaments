// @vitest-environment happy-dom
//
// The card's two images are the whole point of this file.
//
// Both `cover_image_url` and `logo_url` are optional uploads, and an organizer
// who never uploaded either is the common case — so "no image" is a rendering
// contract, not an edge case. Without a cover the card draws the map last
// played in the tournament, before anything is played a still of one of its
// game's maps, and only a game with none gets the drawn name. A grey
// `<img>` with an empty `src` (which every browser resolves against the current
// page and requests) and a decorative placeholder logo are exactly what this
// pins against.
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament } from "@/types/tournament.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));
// `next/image` rewrites src through the optimizer loader; the stand-in keeps
// the stored URL so the test can read it. `fill`/`sizes`/`unoptimized` are
// Next-only props, not DOM attributes.
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
// What a card without a cover is drawn from: the tournament's latest played
// series (its one `useQuery`), and its game's map catalog.
const latest = vi.hoisted(() => ({ data: undefined as unknown, isError: false }));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQuery: () => latest
}));
const catalog = vi.hoisted(() => ({
  data: undefined as unknown[] | undefined,
  isError: false
}));
vi.mock("@/hooks/useCatalogEntities", () => ({
  useCatalogEntities: () => catalog
}));

import TournamentCard from "./TournamentCard";

const MAP_STILL = "https://cdn.example/maps/ilios.jpg";
const PLAYED_MAP = "https://cdn.example/maps/samoa.jpg";

beforeEach(() => {
  // Nothing played yet; the game has one map still.
  latest.data = null;
  latest.isError = false;
  catalog.data = [{ id: 3, name: "Ilios", slug: "ilios", image_path: MAP_STILL, parent: { slug: "control" } }];
  catalog.isError = false;
});

/** Every field spelled out: test files are outside `tsconfig.json`, so a cast
 *  would type-check green over a fixture that is missing what the card reads. */
function tournament(over: Partial<Tournament> = {}): Tournament {
  return {
    id: 42,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: new Date("2026-01-02T00:00:00Z"),
    workspace_id: 1,
    name: "Spring Cup",
    slug: "spring-cup",
    start_date: new Date("2026-02-01T00:00:00Z"),
    end_date: new Date("2026-02-08T00:00:00Z"),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "balancer",
    status: "registration",
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
    logo_url: null,
    ...over
  };
}

function render(over: Partial<Tournament> = {}, games?: Map<string, DisciplineDescriptor>) {
  const html = renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={en}>
      <TournamentCard tournament={tournament(over)} games={games} />
    </NextIntlClientProvider>
  );
  const host = document.createElement("div");
  host.innerHTML = html;
  return host;
}

describe("TournamentCard", () => {
  it("draws the map last played in it when there is no cover", () => {
    latest.data = { matches: [{ id: 9, map_index: 3, map: { id: 7, slug: "samoa", image_path: PLAYED_MAP } }] };
    const host = render();

    expect(host.querySelector("img[data-cover]")?.getAttribute("src")).toBe(PLAYED_MAP);
    expect(host.querySelector("[data-cover-fallback]")).toBeNull();
  });

  it("draws a still of one of its game's maps before anything is played in it", () => {
    expect(render().querySelector("img[data-cover]")?.getAttribute("src")).toBe(MAP_STILL);
  });

  it("keeps the frame empty while it reads, and falls through a read that fails", () => {
    // An empty frame for a moment, rather than a picture flashing in and then
    // swapping for the played map.
    latest.data = undefined;
    const loading = render();
    expect(loading.querySelector("img[data-cover]")).toBeNull();
    expect(loading.querySelector("[data-cover-fallback]")).toBeNull();

    latest.isError = true;
    expect(render().querySelector("img[data-cover]")?.getAttribute("src")).toBe(MAP_STILL);

    catalog.isError = true;
    expect(render().querySelector("[data-cover-fallback]")).toBeTruthy();
  });

  it("renders the uploaded cover when there is one", () => {
    const host = render({ cover_image_url: "https://s3.example/cover.png" });

    expect(host.querySelector("img[data-cover]")?.getAttribute("src")).toBe(
      "https://s3.example/cover.png"
    );
    expect(host.querySelector("img[data-cover]")?.getAttribute("loading")).toBe("lazy");
    expect(host.querySelector("[data-cover-fallback]")).toBeNull();
  });

  it("draws the tournament's name as its cover when its game has no map stills", () => {
    // The fallback is a last kind of cover, not a placeholder — and stays
    // `aria-hidden`, because the `<h3>` below already announces the name.
    catalog.data = [];
    const fallback = render().querySelector("[data-cover-fallback]");

    expect(fallback?.textContent).toContain("Spring Cup");
    expect(fallback?.getAttribute("aria-hidden")).toBe("true");
  });

  it("drops the status chip and the progress bar once a tournament is over", () => {
    // "COMPLETED" beside a permanently full "Final" bar is on most of the grid
    // and distinguishes nothing. A tournament still running earns both.
    const open = render();
    expect(open.textContent).toContain(en.common.statusBadge.registration);
    expect(open.querySelector('[role="progressbar"]')).toBeTruthy();

    const done = render({ status: "completed" });
    expect(done.textContent).not.toContain(en.common.statusBadge.completed);
    expect(done.querySelector('[role="progressbar"]')).toBeNull();
    // The counts are what still tell completed cards apart.
    expect(done.textContent).toContain("30 players");
  });

  it("renders no logo element at all when there is no logo", () => {
    // Not an empty-src `<img>` and not a stand-in glyph: a tournament without a
    // logo shows no logo anywhere on the site.
    expect(render().querySelector("[data-logo]")).toBeNull();
    expect(render({ logo_url: "https://s3.example/logo.png" }).querySelector("[data-logo]"))
      .toBeTruthy();
  });

  it("is a single link to the tournament, with no nested interactive element", () => {
    const host = render();
    const links = host.querySelectorAll("a");

    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/tournaments/spring-cup");
    expect(host.querySelector("button")).toBeNull();
  });

  it("states the participant and team counts", () => {
    const text = render().textContent ?? "";

    expect(text).toContain("30 players");
    expect(text).toContain("6 teams");
  });

  it("omits the team count when the read did not carry one", () => {
    // `teams_count: null` means "entity not requested", not "zero teams".
    expect(render({ teams_count: null }).textContent).not.toContain("0 teams");
  });

  it("names its game only when the list spans several games", () => {
    const games = new Map([
      ["lol", { code: "lol", name: "League of Legends", short_name: "LoL", icon: null } as DisciplineDescriptor]
    ]);

    expect(render({ discipline: "lol" }, games).textContent).toContain("League of Legends");
    expect(render({ discipline: "lol" }).textContent).not.toContain("League of Legends");
  });
});
