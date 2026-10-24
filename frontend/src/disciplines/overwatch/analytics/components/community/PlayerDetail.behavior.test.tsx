// @vitest-environment happy-dom
//
// The player card cites impact only when the viewer has a real v2 score: without one the impact figure, its bar and
// every "why" line that refers to impact are absent.
import fs from "node:fs";
import path from "node:path";

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { OW_METADATA } from "@/test/discipline-metadata";
import type { TournamentAnalytics } from "@/types/analytics.types";
import type { PlayerVM } from "@/disciplines/overwatch/analytics/useAnalyticsViewModel";

import PlayerDetail from "./PlayerDetail";

vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ hasPermission: () => false }) }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface Capture {
  input_old_wire: { analytics: { body: TournamentAnalytics } };
}
const FIXTURE = path.join(__dirname, "..", "..", "..", "__fixtures__", "pre-move", "analytics.tournament.linear.json");
// A frozen analytics-service response, never edited: its body is the wire type.
const CAPTURE = JSON.parse(fs.readFileSync(FIXTURE, "utf8")) as Capture;
const BASE = CAPTURE.input_old_wire.analytics.body.teams[0].players[0];

const WHY = messages.analytics.community.why;
/** The fixed text of a `why` message up to its first placeholder. */
const lead = (message: string) => message.split("{")[0];

let root: Root | null = null;
let container: HTMLElement;

function render(direction: PlayerVM["predicted_direction"], impact: number | null) {
  const player: PlayerVM = { ...BASE, predicted_direction: direction, anomalies: [], impact };
  act(() => {
    root = createRoot(container);
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PlayerDetail player={player} teamName="Alpha" ontology={OW_METADATA} onExplain={() => {}} />
      </NextIntlClientProvider>
    );
  });
  return container.textContent ?? "";
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container.remove();
});

describe("PlayerDetail impact copy", () => {
  it("says nothing about impact on a climb or drop without a v2 score", () => {
    const climb = render("promote", null);
    expect(climb).not.toContain(lead(WHY.climbImpact));
    expect(climb).toContain(lead(WHY.climbConfidence));
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
    act(() => root?.unmount());

    const drop = render("demote", null);
    expect(drop).not.toContain(lead(WHY.dropImpact));
    expect(drop).toContain(lead(WHY.dropConsistent));
  });

  it("cites impact when the viewer's v2 score is in the matching bucket", () => {
    expect(render("promote", 85)).toContain(lead(WHY.climbImpact));
    expect(container.querySelector('[role="progressbar"]')).not.toBeNull();
    act(() => root?.unmount());

    expect(render("demote", 20)).toContain(lead(WHY.dropImpact));
  });

  it("never claims an impact the score contradicts", () => {
    const climb = render("promote", 20);
    expect(climb).not.toContain(lead(WHY.climbImpact));
    expect(climb).toContain(lead(WHY.climbConfidence));
    act(() => root?.unmount());

    const drop = render("demote", 85);
    expect(drop).not.toContain(lead(WHY.dropImpact));
    expect(drop).toContain(lead(WHY.dropConsistent));
  });
});
