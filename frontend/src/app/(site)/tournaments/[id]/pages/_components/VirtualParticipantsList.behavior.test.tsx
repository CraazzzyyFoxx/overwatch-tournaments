import { afterAll, beforeAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act } from "react";

import type { Registration } from "@/types/registration.types";

import type { ColumnDefinition } from "./participantsColumns";

const testWindow = new Window({
  url: "http://localhost:3000/tournaments/72/participants",
  width: 1280,
  height: 900
});
const globals = globalThis as typeof globalThis & Record<string, unknown>;
const previousGlobals = new Map<string, unknown>();

class TestResizeObserver {
  readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    const rect = target.getBoundingClientRect();
    this.callback(
      [
        {
          target,
          contentRect: rect,
          borderBoxSize: [
            {
              blockSize: rect.height,
              inlineSize: rect.width
            }
          ],
          contentBoxSize: [
            {
              blockSize: rect.height,
              inlineSize: rect.width
            }
          ],
          devicePixelContentBoxSize: []
        } as unknown as ResizeObserverEntry
      ],
      this as unknown as ResizeObserver
    );
  }

  disconnect() {}
  unobserve() {}
}

const originalWindowResizeObserver = testWindow.ResizeObserver;
(testWindow as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  TestResizeObserver as unknown as typeof ResizeObserver;

for (const [key, value] of Object.entries({
  window: testWindow,
  document: testWindow.document,
  navigator: testWindow.navigator,
  HTMLElement: testWindow.HTMLElement,
  Event: testWindow.Event,
  Node: testWindow.Node,
  MutationObserver: testWindow.MutationObserver,
  ResizeObserver: TestResizeObserver,
  getComputedStyle: testWindow.getComputedStyle.bind(testWindow),
  requestAnimationFrame: testWindow.requestAnimationFrame.bind(testWindow),
  cancelAnimationFrame: testWindow.cancelAnimationFrame.bind(testWindow),
  IS_REACT_ACT_ENVIRONMENT: true
})) {
  previousGlobals.set(key, globals[key]);
  globals[key] = value;
}

mock.module("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));
mock.module("@/components/BattleTagRankHistory", () => ({
  default: () => null
}));

const { createRoot } = await import("react-dom/client");
const { default: VirtualParticipantsList } = await import("./VirtualParticipantsList");

const originalBoundingRect = testWindow.HTMLElement.prototype.getBoundingClientRect;
const originalOffsetHeight = Object.getOwnPropertyDescriptor(
  testWindow.HTMLElement.prototype,
  "offsetHeight"
);

function registration(id: number): Registration {
  return {
    id,
    tournament_id: 72,
    workspace_id: 1,
    user_id: id,
    battle_tag: `Player${id}#1234`,
    smurf_tags_json: null,
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles: [],
    notes: null,
    custom_fields_json: null,
    status: "approved",
    submitted_at: null,
    reviewed_at: null
  };
}

const registrations = Array.from({ length: 500 }, (_, index) => registration(index + 1));
const imageColumn: ColumnDefinition = {
  id: "battle_tag",
  label: "Player",
  category: "built_in",
  defaultVisible: true,
  render: (row) => (
    // eslint-disable-next-line @next/next/no-img-element -- verifies image DOM mount cost
    <img
      alt={row.battle_tag ?? "Player"}
      data-registration-image={row.id}
      src={`/avatars/${row.id}.png`}
    />
  )
};

beforeAll(() => {
  Object.defineProperty(testWindow.HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return this.hasAttribute("data-index") ? 68 : 0;
    }
  });
  testWindow.HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
    const height = this.hasAttribute("data-index") ? 68 : 0;
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      width: 1280,
      height,
      right: 1280,
      bottom: height,
      toJSON: () => ({})
    } as DOMRect;
  };
});

afterAll(async () => {
  testWindow.HTMLElement.prototype.getBoundingClientRect = originalBoundingRect;
  if (originalOffsetHeight) {
    Object.defineProperty(testWindow.HTMLElement.prototype, "offsetHeight", originalOffsetHeight);
  }
  (testWindow as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    originalWindowResizeObserver;
  mock.restore();
  await testWindow.close();
  for (const [key, value] of previousGlobals) {
    if (value === undefined) delete globals[key];
    else globals[key] = value;
  }
});

describe("VirtualParticipantsList mount budget", () => {
  it("renders a bounded window for 500 registrations without far-row images", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <VirtualParticipantsList
          allColumns={[imageColumn]}
          expandedIds={new Set()}
          onToggleExpanded={() => {}}
          registrations={registrations}
          visibleColumns={[imageColumn]}
        />
      );
      window.dispatchEvent(new testWindow.Event("resize"));
      await new Promise<void>((resolve) => testWindow.requestAnimationFrame(() => resolve()));
    });

    const table = container.querySelector('[role="table"]');
    const mountedRows = container.querySelectorAll("[data-index]");
    const mountedImages = container.querySelectorAll("[data-registration-image]");

    expect(table?.getAttribute("aria-rowcount")).toBe("501");
    expect(mountedRows.length).toBeGreaterThan(0);
    expect(mountedRows.length).toBeLessThanOrEqual(40);
    expect(mountedImages.length).toBe(mountedRows.length);
    expect(container.querySelector('[data-registration-image="500"]')).toBeNull();
    expect(container.querySelector('[data-index="499"]')).toBeNull();

    act(() => root.unmount());
    container.remove();
  });
});
