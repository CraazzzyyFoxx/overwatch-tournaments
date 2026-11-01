// @vitest-environment happy-dom
//
// The drag preview is the seat itself, lifted off the list: a captain dragged
// across the matchup keeps the crown (spec §7.2), and nobody else gains one.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OW_OWNER } from "../mix-owner.fixture";
import type { PickupSeat } from "../pickup-lineup";
import { SeatDragPreview } from "./SeatRow";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { has: () => false }),
}));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));

function seat(overrides: Partial<PickupSeat> = {}): PickupSeat {
  return {
    uuid: "8",
    name: "DemonDimon",
    display: { name: "DemonDimon", tag: null, canonical: null, snapshot: null },
    role: "tank",
    rating: 3900,
    openRating: null,
    offRole: false,
    isFlex: false,
    isCaptain: false,
    subRole: null,
    ...overrides,
  };
}

async function mountPreview(value: PickupSeat) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(<SeatDragPreview seat={value} owner={OW_OWNER} />);
  });
  return container;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("SeatDragPreview", () => {
  it("keeps the captain's crown on a dragged captain", async () => {
    const scope = await mountPreview(seat({ isCaptain: true }));

    expect(scope.textContent).toContain("DemonDimon");
    expect(scope.querySelector('[role="img"][aria-label="captain"]')).not.toBeNull();
  });

  it("draws no crown on a dragged seat that is not the captain", async () => {
    const scope = await mountPreview(seat());

    expect(scope.textContent).toContain("DemonDimon");
    expect(scope.querySelector('[aria-label="captain"]')).toBeNull();
  });
});
