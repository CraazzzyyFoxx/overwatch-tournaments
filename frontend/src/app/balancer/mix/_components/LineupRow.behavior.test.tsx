// @vitest-environment happy-dom
//
// The rotation hint's tooltip is worded here, from the server's reason CODE and
// the count beside it. The server used to send a finished Russian sentence
// ("Сыграл 3 карт(ы) подряд"), which an English host read verbatim.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { CustomGamePlayer, RotationRecommendation } from "@/services/custom-game.service";

import { OW_OWNER } from "../mix-owner.fixture";
import { LineupRow } from "./LineupRow";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@dnd-kit/core", () => ({
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false })
}));

const ROW: CustomGamePlayer = {
  id: 1,
  workspace_member_id: 7,
  display_name: null,
  display: { name: "Aria#1111", tag: null, canonical: "Aria#1111", snapshot: null },
  identity: { provider: "battlenet", handle: "Aria#1111" },
  sort_order: 0,
  participation: "pool",
  roles: null,
  ranks: { tank: 2400, damage: 2600, support: 2500 },
  rank_sources: { tank: "workspace", damage: "workspace", support: "workspace" },
  author_ranks: {}
};

function hint(overrides: Partial<RotationRecommendation>): RotationRecommendation {
  return {
    workspace_member_id: 7,
    status: "must_play",
    reason: "owed_seat",
    consecutive_sat: 0,
    consecutive_played: 0,
    games_played: 0,
    ...overrides
  };
}

/** Every accessible image label the row renders; the rotation hint is one of them. */
async function labelsOf(locale: "en" | "ru", rotationHint: RotationRecommendation): Promise<(string | null)[]> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : ru}>
        <ul>
          <LineupRow
            row={ROW}
            rotationHint={rotationHint}
            owner={OW_OWNER}
            canWrite
            lobbyCount={1}
            saving={false}
            dimmed={false}
            onPatch={() => {}}
            onOpen={() => {}}
            onRemove={() => {}}
          />
        </ul>
      </NextIntlClientProvider>
    );
  });
  return [...container.querySelectorAll('[role="img"][aria-label]')].map((node) => node.getAttribute("aria-label"));
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("LineupRow rotation hint", () => {
  it("words an owed seat with the sat-out streak, in English", async () => {
    expect(await labelsOf("en", hint({ reason: "owed_seat", consecutive_sat: 2 }))).toContain(
      "Sat out 2 maps in a row — next to play"
    );
  });

  it("words an owed seat in Russian with the right plural", async () => {
    expect(await labelsOf("ru", hint({ reason: "owed_seat", consecutive_sat: 1 }))).toContain(
      "Сидел 1 карту подряд — очередь играть"
    );
  });

  it("words a should-rest streak from consecutive_played", async () => {
    const rest = hint({ status: "should_rest", reason: "played_streak", consecutive_played: 3, games_played: 5 });
    expect(await labelsOf("en", rest)).toContain("Played 3 maps in a row");
    expect(await labelsOf("ru", rest)).toContain("Сыграл 3 карты подряд");
  });

  it("words a should-rest by volume from games_played", async () => {
    const rest = hint({ status: "should_rest", reason: "played_most", games_played: 5 });
    expect(await labelsOf("en", rest)).toContain("Played 5 maps — time to give up the seat");
    expect(await labelsOf("ru", rest)).toContain("Сыграл 5 карт — пора уступить место");
  });
});
