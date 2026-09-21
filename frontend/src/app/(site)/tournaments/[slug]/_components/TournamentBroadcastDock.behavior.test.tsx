// @vitest-environment happy-dom
//
// `embeddable` is true only for `live`, so between series the dock has a frame
// it cannot fill and shows a bare "Watch on …" link — while participants may be
// on air the whole time. The dock USED to borrow the busiest participant's POV
// for the frame; it no longer does. This corner is the organizer's broadcast on
// every section of the page, and a one-sided POV standing in for the cast reads
// as the cast however it is captioned — participant streams belong to the
// Stream section, where the viewer picks the POV.
//
// What is pinned here:
//
//  1. no participant ever reaches the frame, however many viewers they have and
//     however offline the official channel is;
//  2. with no embeddable official entry the panel degrades to the link, not to
//     someone else's stream;
//  3. the panel is only ever named the official broadcast.
import { NextIntlClientProvider } from "next-intl";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import type { StreamEntry, TournamentStreams } from "@/types/stream.types";

import { TournamentBroadcastDock } from "./TournamentBroadcastDock";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let unmount: (() => void) | null = null;

/**
 * Every field spelled out rather than cast into place: `tsconfig.json` excludes
 * test files, so a fixture that lies about its shape type-checks green and
 * feeds the component a hole.
 */
function streamEntry(overrides: Partial<StreamEntry> = {}): StreamEntry {
  return {
    platform: "twitch",
    channel: "somechannel",
    url: "https://twitch.tv/somechannel",
    live: true,
    title: null,
    game_name: "Overwatch 2",
    viewer_count: null,
    thumbnail_url: null,
    started_at: null,
    player: null,
    ...overrides
  };
}

function participant(channel: string, viewerCount: number | null, name = channel): StreamEntry {
  return streamEntry({
    channel,
    url: `https://twitch.tv/${channel}`,
    viewer_count: viewerCount,
    player: { id: 1, name, avatar_url: null, team: null }
  });
}

function render(streams: TournamentStreams) {
  const root = createRoot(container);
  act(() =>
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <TournamentBroadcastDock streams={streams} />
      </NextIntlClientProvider>
    )
  );
  unmount = () => act(() => root.unmount());
}

/** The Twitch login currently in the frame, or `null` when nothing plays. */
function playingChannel(streams: TournamentStreams): string | null {
  render(streams);
  reveal();
  const src = document.body.querySelector("iframe")?.getAttribute("src");
  return src ? new URL(src).searchParams.get("channel") : null;
}

function control(label: string): HTMLButtonElement | null {
  return (
    [...document.body.querySelectorAll("button")].find(
      (button) =>
        button.getAttribute("aria-label") === label || button.textContent?.includes(label)
    ) ?? null
  );
}

function reveal() {
  const restore = control(en.stream.broadcast.show);
  if (restore) {
    act(() => restore.click());
  }
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  unmount?.();
  unmount = null;
  container.remove();
});

describe("TournamentBroadcastDock featured pick", () => {
  it("keeps a live official cast in the frame over a bigger participant", () => {
    expect(
      playingChannel({
        official: [streamEntry({ channel: "owtcast", viewer_count: 40 })],
        participants: [participant("bigstreamer", 9000)]
      })
    ).toBe("owtcast");
  });

  it("never borrows a participant's frame, however dead the official channel is", () => {
    expect(
      playingChannel({
        official: [streamEntry({ channel: "owtcast", live: false })],
        participants: [participant("quietone", 3), participant("bigstreamer", 900)]
      })
    ).toBeNull();
  });

  it("still offers the link when nothing at all can be embedded", () => {
    render({
      official: [
        streamEntry({
          platform: "youtube",
          channel: "owtcast",
          url: "https://youtube.com/@owtcast",
          live: null
        })
      ],
      participants: [participant("bigstreamer", 900)]
    });
    reveal();

    expect(document.body.querySelector("iframe")).toBeNull();
    expect(document.body.textContent).toContain(
      en.stream.broadcast.watchOn.replace("{platform}", "YouTube")
    );
  });
});

describe("TournamentBroadcastDock naming", () => {
  const streams: TournamentStreams = {
    official: [
      streamEntry({
        channel: "owtcast",
        url: "https://twitch.tv/owtcast",
        live: false
      })
    ],
    participants: [
      streamEntry({
        channel: "somestreamer",
        url: "https://twitch.tv/somestreamer",
        viewer_count: 42,
        player: { id: 5, name: "someplayer", avatar_url: null, team: { id: 3, name: "Alpha" } }
      })
    ]
  };

  it("is the official broadcast even when the cast is off air", () => {
    render(streams);
    reveal();
    const text = document.body.textContent ?? "";

    expect(text).toContain(en.stream.broadcast.heading);
    // Not a word about the participant who is live right now.
    expect(text).not.toContain("somestreamer");
    expect(text).not.toContain("someplayer");
  });

  // The cast lost the frame, not its link: it is still where a spectator goes
  // when the broadcast comes back.
  it("keeps every official link reachable", () => {
    render(streams);
    reveal();

    expect(document.body.querySelector('a[href="https://twitch.tv/owtcast"]')).not.toBeNull();
  });
});

// A corner panel is watched, not read. The channel's own title used to sit
// under the frame and said nothing the heading, the live pill and Twitch's own
// overlay were not already saying — for two more lines of a 380px panel. With
// it gone, the footer has to disappear WITH it in the ordinary case, or the
// panel keeps a 24px padded strip of nothing under the video.
describe("TournamentBroadcastDock panel body", () => {
  it("shows no stream description under the frame", () => {
    render({
      official: [
        streamEntry({
          channel: "owtcast",
          url: "https://twitch.tv/owtcast",
          title: "[DROPS] day two, watch the finals"
        })
      ],
      participants: []
    });
    reveal();

    expect(document.body.textContent).not.toContain("[DROPS] day two, watch the finals");
  });

  it("ends at the frame when there is nothing else to say", () => {
    render({
      official: [
        streamEntry({ channel: "owtcast", url: "https://twitch.tv/owtcast", title: "a title" })
      ],
      participants: []
    });
    reveal();

    // Header, then the frame's ratio box — and nothing after it.
    expect(document.body.querySelector("aside")?.children).toHaveLength(2);
  });

  // The footer is not dead code: it still carries what the frame cannot say.
  it("keeps the footer for the other official channels", () => {
    render({
      official: [
        streamEntry({ channel: "owtcast", url: "https://twitch.tv/owtcast" }),
        streamEntry({ channel: "owtcast2", url: "https://twitch.tv/owtcast2" })
      ],
      participants: []
    });
    reveal();

    expect(document.body.querySelector('a[href="https://twitch.tv/owtcast2"]')).not.toBeNull();
  });
});

// Dismissing a floating player has two ways to go wrong, and both are silent.
// If "hide" only styled the panel away, the iframe would keep streaming to a
// viewer who asked it to stop — the whole point of the control is the
// bandwidth. And because both controls unmount the moment they are used,
// focus falls to <body> unless it is moved explicitly, which restarts a
// keyboard user's traversal at the top of the document on every toggle.
describe("TournamentBroadcastDock hide and restore", () => {
  const streams: TournamentStreams = {
    official: [streamEntry({ channel: "owtcast", url: "https://twitch.tv/owtcast" })],
    participants: []
  };

  it("starts collapsed, with the restore control and no frame", () => {
    render(streams);

    expect(document.body.querySelector("iframe")).toBeNull();
    expect(control(en.stream.broadcast.show)).not.toBeNull();
  });

  // The dock arrives on every section of the tournament; taking focus would
  // move the caret out from under whoever was already reading.
  it("takes no focus when it mounts", () => {
    render(streams);

    expect(document.activeElement).toBe(document.body);
  });

  it("unmounts the player when hidden, rather than parking it out of sight", () => {
    render(streams);
    reveal();

    act(() => control(en.stream.broadcast.hide)?.click());

    expect(document.body.querySelector("iframe")).toBeNull();
  });

  it("keeps the broadcast one click away after hiding", () => {
    render(streams);

    const restore = control(en.stream.broadcast.show);
    expect(restore).not.toBeNull();

    act(() => restore?.click());
    expect(document.body.querySelector("iframe")?.getAttribute("src")).toContain("channel=owtcast");
  });

  it("moves focus to the restore control when the panel goes away", () => {
    render(streams);
    reveal();

    act(() => control(en.stream.broadcast.hide)?.click());

    expect(document.activeElement).toBe(control(en.stream.broadcast.show));
  });

  it("moves focus to the close control when the panel comes back", () => {
    render(streams);
    reveal();
    act(() => control(en.stream.broadcast.hide)?.click());

    act(() => control(en.stream.broadcast.show)?.click());

    expect(document.activeElement).toBe(control(en.stream.broadcast.hide));
  });

  // Escape is the convenience for whoever is already inside the panel. It is
  // NOT a modal: nothing is trapped, so this must not be the only way out.
  it("closes on Escape from inside the panel", () => {
    render(streams);
    reveal();

    act(() => {
      document.body
        .querySelector("aside")
        ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    expect(document.body.querySelector("iframe")).toBeNull();
  });

  it("announces itself as a landmark rather than a modal dialog", () => {
    render(streams);
    reveal();
    const panel = document.body.querySelector("aside");

    expect(panel?.getAttribute("aria-label")).toBe(en.stream.broadcast.heading);
    expect(panel?.getAttribute("aria-modal")).toBeNull();
  });
});
