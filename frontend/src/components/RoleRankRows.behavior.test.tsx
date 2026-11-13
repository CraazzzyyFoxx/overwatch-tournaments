// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";

vi.mock("@/hooks/useCurrentWorkspace", () => ({ useDivisionGrid: () => ({ tiers: [] }) }));

import { RoleRankRows } from "./RoleRankRows";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let unmount: () => void;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
});
afterEach(() => {
  unmount();
  container.remove();
});

const dim = "rating";

describe("RoleRankRows", () => {
  it("numbers roles by priority and says why a role is not playable", () => {
    const root = createRoot(container);
    act(() =>
      root.render(
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <RoleRankRows
            grid={{ tiers: [] }}
            ontology={null}
            rows={[
              { role: { dimension: dim, role: "damage" }, rank: 3600, primary: true, source: "registration", gameRank: 3450 },
              { role: { dimension: dim, role: "support" }, rank: 3500, source: "native", gameRank: 3500 },
              { role: { dimension: dim, role: "tank" }, rank: null, source: "none" }
            ]}
          />
        </NextIntlClientProvider>
      )
    );
    unmount = () => act(() => root.unmount());

    const rows = [...container.querySelectorAll("li")].map((li) => li.textContent);
    expect(rows).toEqual([
      "1?damageMain3600from registration · In game 3450",
      // `?` is the glyph of a role no dictionary names. The game rank equals the rank: printing it again says nothing.
      "2?support3500from the game",
      "3?tankNo rank — not playable"
    ]);
  });
});
