// @vitest-environment happy-dom
//
// The Twitch player has exactly one way to fail silently: a `parent` that does
// not match the domain framing it. Twitch answers a mismatch with a blank
// player and no error we can observe, and this platform serves the same page on
// the apex, on `*.owt.craazzzyyfoxx.me` subdomains and on arbitrary tenant
// custom domains — so a build-time host (NEXT_PUBLIC_SITE_URL) is wrong for
// every custom-domain tenant. These tests pin the three properties that keep
// the frame playable.
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PLATFORM_ZONE } from "@/lib/site/host";

import { TwitchEmbed, twitchParentFromHostname } from "./TwitchEmbed";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;

function render(ui: React.ReactNode) {
  const root = createRoot(container);
  act(() => root.render(ui));
  return () => act(() => root.unmount());
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  container.remove();
});

describe("twitchParentFromHostname", () => {
  // Twitch rejects a `parent` carrying a port, so dev on localhost:3000 must
  // send plain `localhost` or the player never plays locally.
  it("strips the port", () => {
    expect(twitchParentFromHostname("localhost:3000")).toBe("localhost");
    expect(twitchParentFromHostname("tenant.example.com:8443")).toBe("tenant.example.com");
  });

  it("lowercases and trims", () => {
    expect(twitchParentFromHostname("  Tenant.EXAMPLE.Com  ")).toBe("tenant.example.com");
  });

  it("yields null for an absent host, so the caller renders no player", () => {
    expect(twitchParentFromHostname("")).toBeNull();
    expect(twitchParentFromHostname(null)).toBeNull();
    expect(twitchParentFromHostname(undefined)).toBeNull();
  });
});

describe("TwitchEmbed", () => {
  // The platform apex is what a build-time host (NEXT_PUBLIC_SITE_URL) would
  // yield; the frame must carry the host actually serving the document, which is
  // the only value Twitch will accept on a tenant's custom domain.
  it("takes parent from the live document host, not the platform apex", () => {
    render(<TwitchEmbed channel="somestreamer" />);

    const src = container.querySelector("iframe")?.getAttribute("src") ?? "";
    const params = new URL(src).searchParams;
    expect(params.get("parent")).toBe(window.location.hostname);
    expect(params.get("parent")).not.toBe(PLATFORM_ZONE);
  });

  // Autoplay with sound is blocked by browsers anyway; asking for muted playback
  // is what makes the player start on its own.
  it("asks for muted playback and the requested channel", () => {
    render(<TwitchEmbed channel="SomeStreamer" />);

    const src = container.querySelector("iframe")?.getAttribute("src") ?? "";
    expect(src).toContain("muted=true");
    expect(new URL(src).searchParams.get("channel")).toBe("SomeStreamer");
  });

  it("names the frame for assistive tech", () => {
    render(<TwitchEmbed channel="somestreamer" />);

    expect(container.querySelector("iframe")?.getAttribute("title")).toBe("Twitch · somestreamer");
  });

  // The server has no hostname. Emitting a frame with a guessed `parent` would
  // be a dead player that never recovers, so nothing renders until the effect
  // has read the real host.
  it("renders no iframe before mount", () => {
    expect(renderToStaticMarkup(<TwitchEmbed channel="somestreamer" />)).toBe("");
  });

  it("renders no iframe without a channel", () => {
    render(<TwitchEmbed channel="" />);

    expect(container.querySelector("iframe")).toBeNull();
  });
});
