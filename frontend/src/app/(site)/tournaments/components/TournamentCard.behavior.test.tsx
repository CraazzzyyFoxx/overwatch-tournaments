// @vitest-environment happy-dom
//
// The card's two images are the whole point of this file.
//
// Both `cover_image_url` and `logo_url` are optional uploads, and an organizer
// who never uploaded either is the common case — so "no image" is a rendering
// contract, not an edge case. A grey `<img>` with an empty `src` (which every
// browser resolves against the current page and requests) and a decorative
// placeholder logo are exactly what this pins against.
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament } from "@/types/tournament.types";

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

import TournamentCard from "./TournamentCard";

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
    roster_slots_json: null,
    roster_shape: null,
    roster_locked_by_draft: null,
    cover_image_url: null,
    logo_url: null,
    ...over
  };
}

function render(over: Partial<Tournament> = {}) {
  const html = renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={en}>
      <TournamentCard tournament={tournament(over)} />
    </NextIntlClientProvider>
  );
  const host = document.createElement("div");
  host.innerHTML = html;
  return host;
}

describe("TournamentCard", () => {
  it("renders the placeholder instead of an image when there is no cover", () => {
    const host = render();

    expect(host.querySelector("img[data-cover]")).toBeNull();
    expect(host.querySelector("[data-cover-fallback]")).toBeTruthy();
  });

  it("renders the uploaded cover when there is one", () => {
    const host = render({ cover_image_url: "https://s3.example/cover.png" });

    expect(host.querySelector("img[data-cover]")?.getAttribute("src")).toBe(
      "https://s3.example/cover.png"
    );
    expect(host.querySelector("img[data-cover]")?.getAttribute("loading")).toBe("lazy");
    expect(host.querySelector("[data-cover-fallback]")).toBeNull();
  });

  it("draws the tournament's name as its cover when there is no image", () => {
    // The fallback is a second kind of cover, not a placeholder — and stays
    // `aria-hidden`, because the `<h3>` below already announces the name.
    const fallback = render().querySelector("[data-cover-fallback]");

    expect(fallback?.textContent).toContain("Spring Cup");
    expect(fallback?.getAttribute("aria-hidden")).toBe("true");
  });

  it("drops the status chip and the progress bar once a tournament is over", () => {
    // "COMPLETED" beside a permanently full "Final" bar is on most of the grid
    // and distinguishes nothing. A tournament still running earns both.
    const open = render();
    expect(open.querySelector(".tn-status")).toBeTruthy();
    expect(open.querySelector(".tn-stage")).toBeTruthy();

    const done = render({ status: "completed" });
    expect(done.querySelector(".tn-status")).toBeNull();
    expect(done.querySelector(".tn-stage")).toBeNull();
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
});
