// @vitest-environment happy-dom
//
// The client host of one optional module slot (P7 contracts §7). Backend capability and local renderer
// are separate facts:
//  - a capability the game does not have says so, and loads nothing;
//  - a native shape the slot does not apply to renders the generic fallback;
//  - a promised capability whose renderer is missing is an explicit error, never a silent fallback;
//  - without a required capability a missing renderer simply shows the generic fallback;
//  - an unknown game never resolves to another game's module;
//  - a module that failed to load is a retryable error, never the "no renderer" fallback.
import { NextIntlClientProvider } from "next-intl";
import { act, lazy, type ComponentProps, type ReactNode } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";

import { DisciplineWidget as Host } from "./DisciplineWidget";
import type { DisciplineLoader } from "./registry/create";
import type { DisciplineCapabilities, DisciplineSlot, DisciplineUI, SlotProps } from "./types";

// The host takes its family's loader as a prop; the test supplies a controllable one, unsettled unless a case says so.
const loadDisciplineUI = vi.fn<(code: string) => Promise<DisciplineUI | null>>();
const peekDisciplineUI = vi.fn<DisciplineLoader<DisciplineSlot>["peek"]>();
const load: DisciplineLoader<DisciplineSlot> = Object.assign(loadDisciplineUI, { peek: peekDisciplineUI });
function DisciplineWidget(props: Omit<ComponentProps<typeof Host>, "load">) {
  return <Host {...props} load={load} />;
}

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const NONE: DisciplineCapabilities = {
  catalog_sync: false,
  native_rank_collection: false,
  native_ladder: false,
  achievement_conditions: false,
  analytics: false
};
const LADDER: DisciplineCapabilities = { ...NONE, native_ladder: true };
const EDITOR_PROPS: SlotProps["nativeRankEditor"] = { ladder: [], value: null, onChange: () => {} };

/** A module whose `nativeRankEditor` renders its own code, so a wrong game's module is visible. */
function moduleOf(code: string): DisciplineUI {
  return {
    code,
    slots: {
      nativeRankEditor: lazy(async () => ({
        default: ({ disabled }: SlotProps["nativeRankEditor"]) => (
          <p data-slot={code}>{`${code} editor${disabled ? " (disabled)" : ""}`}</p>
        )
      }))
    }
  };
}

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 5) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        {node}
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

afterEach(() => {
  for (const { root, container } of mounted.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  loadDisciplineUI.mockReset();
  peekDisciplineUI.mockReset();
});

describe("DisciplineWidget", () => {
  it("renders the slot of the game it was asked for, with the caller's props", async () => {
    loadDisciplineUI.mockImplementation(async (code) => moduleOf(code));

    const view = await mount(
      <DisciplineWidget
        discipline="overwatch"
        slot="nativeRankEditor"
        capabilities={LADDER}
        requires="native_ladder"
        props={{ ...EDITOR_PROPS, disabled: true }}
        fallback={<p>generic</p>}
      />
    );

    expect(view.querySelector("[data-slot]")?.textContent).toBe("overwatch editor (disabled)");
    expect(loadDisciplineUI).toHaveBeenCalledWith("overwatch");
    expect(view.textContent).not.toContain("generic");
  });

  it("says so, and loads nothing, when the game lacks the required capability", async () => {
    loadDisciplineUI.mockImplementation(async (code) => moduleOf(code));

    const view = await mount(
      <DisciplineWidget
        discipline="lol"
        slot="nativeRankEditor"
        capabilities={NONE}
        requires="native_ladder"
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    expect(view.textContent).toContain(en.common.discipline.widgetUnsupported);
    expect(view.querySelector("[role=alert]")).toBeNull();
    expect(loadDisciplineUI).not.toHaveBeenCalled();
  });

  it("is a configuration error when a promised capability has no renderer in the module", async () => {
    loadDisciplineUI.mockResolvedValue({ code: "lol", slots: {} });

    const view = await mount(
      <DisciplineWidget
        discipline="lol"
        slot="nativeRankEditor"
        capabilities={LADDER}
        requires="native_ladder"
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    expect(view.querySelector("[role=alert]")?.textContent).toBe(en.common.discipline.widgetMissing);
    expect(view.textContent).not.toContain("generic");
  });

  it("is the same configuration error when the game has no module at all — never another game's", async () => {
    loadDisciplineUI.mockImplementation(async (code) => (code === "overwatch" ? moduleOf(code) : null));

    const view = await mount(
      <DisciplineWidget
        discipline="chess"
        slot="nativeRankEditor"
        capabilities={LADDER}
        requires="native_ladder"
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    expect(view.querySelector("[role=alert]")).not.toBeNull();
    expect(view.querySelector("[data-slot]")).toBeNull();
  });

  it("shows the generic fallback when nothing is required and the module has no renderer", async () => {
    loadDisciplineUI.mockResolvedValue({ code: "lol", slots: {} });

    const view = await mount(
      <DisciplineWidget
        discipline="lol"
        slot="nativeRankEditor"
        capabilities={NONE}
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    expect(view.textContent).toContain("generic");
    expect(view.querySelector("[role=alert]")).toBeNull();
  });

  it("shows nothing while the module is still resolving, and the fallback only once it has none", async () => {
    const pending = Promise.withResolvers<{ code: string; slots: object } | null>();
    loadDisciplineUI.mockReturnValue(pending.promise);

    const view = await mount(
      <DisciplineWidget
        discipline="lol"
        slot="nativeRankEditor"
        capabilities={NONE}
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );
    expect(view.textContent).not.toContain("generic");
    expect(view.querySelector("[role=alert]")).toBeNull();

    await act(async () => pending.resolve(null));
    expect(view.textContent).toContain("generic");
  });

  it("shows the caller's pending view while the module resolves, then the slot in its place", async () => {
    const pending = Promise.withResolvers<DisciplineUI | null>();
    loadDisciplineUI.mockReturnValue(pending.promise);

    const view = await mount(
      <DisciplineWidget
        discipline="overwatch"
        slot="nativeRankEditor"
        capabilities={LADDER}
        requires="native_ladder"
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
        pending={<p>loading board</p>}
      />
    );
    expect(view.textContent).toBe("loading board");

    await act(async () => pending.resolve(moduleOf("overwatch")));
    await settle();
    expect(view.textContent).toBe("overwatch editor");
  });

  it("shows the generic fallback, and loads nothing, for a shape the slot does not apply to", async () => {
    loadDisciplineUI.mockImplementation(async (code) => moduleOf(code));

    const view = await mount(
      <DisciplineWidget
        discipline="overwatch"
        slot="nativeRankEditor"
        capabilities={LADDER}
        applicable={false}
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    expect(view.textContent).toContain("generic");
    expect(view.querySelector("[data-slot]")).toBeNull();
    expect(loadDisciplineUI).not.toHaveBeenCalled();
  });

  it("follows the game: a changed discipline never keeps the previous game's slot on screen", async () => {
    loadDisciplineUI.mockImplementation(async (code) => moduleOf(code));
    const render = (discipline: string) => (
      <DisciplineWidget
        discipline={discipline}
        slot="nativeRankEditor"
        capabilities={LADDER}
        requires="native_ladder"
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    const show = async (discipline: string) => {
      await act(async () => {
        root.render(
          <NextIntlClientProvider locale="en" messages={en}>
            {render(discipline)}
          </NextIntlClientProvider>
        );
      });
      await settle();
    };

    await show("overwatch");
    expect(container.querySelector("[data-slot]")?.getAttribute("data-slot")).toBe("overwatch");

    loadDisciplineUI.mockImplementation(async (code) => (code === "overwatch" ? moduleOf(code) : { code, slots: {} }));
    await show("lol");

    expect(container.querySelector("[data-slot]")).toBeNull();
    expect(container.querySelector("[role=alert]")?.textContent).toBe(en.common.discipline.widgetMissing);
  });

  it("tells a module that failed to load from one that has no renderer, and retries it", async () => {
    loadDisciplineUI.mockRejectedValueOnce(new Error("ChunkLoadError"));
    loadDisciplineUI.mockImplementation(async (code) => moduleOf(code));

    const view = await mount(
      <DisciplineWidget
        discipline="overwatch"
        slot="nativeRankEditor"
        capabilities={NONE}
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );

    const alert = view.querySelector("[role=alert]");
    expect(alert?.textContent).toContain(en.common.discipline.widgetLoadFailed);
    expect(view.textContent).not.toContain("generic");
    expect(view.querySelector("[data-slot]:not([data-slot='button'])")).toBeNull();

    await act(async () => alert?.querySelector("button")?.click());
    await settle();

    expect(loadDisciplineUI).toHaveBeenCalledTimes(2);
    expect(view.querySelector("[data-slot]")?.textContent).toBe("overwatch editor");
    expect(view.querySelector("[role=alert]")).toBeNull();
  });

  it("paints an already-settled module on its first commit — a re-mounted hover card never flashes empty", async () => {
    const ui = moduleOf("overwatch");
    loadDisciplineUI.mockResolvedValue(ui);
    const widget = (
      <DisciplineWidget
        discipline="overwatch"
        slot="nativeRankEditor"
        capabilities={NONE}
        props={EDITOR_PROPS}
        fallback={<p>generic</p>}
      />
    );
    // The first open: the module and its lazy slot resolve.
    await mount(widget);
    peekDisciplineUI.mockReturnValue(ui);

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    act(() =>
      root.render(
        <NextIntlClientProvider locale="en" messages={en}>
          {widget}
        </NextIntlClientProvider>
      )
    );

    expect(container.querySelector("[data-slot]")?.textContent).toBe("overwatch editor");
    expect(loadDisciplineUI).toHaveBeenCalledTimes(1);
  });

  it("hydrates what the server rendered when the module settled in the browser first", async () => {
    // The server never loads a module; another widget on the page can settle it before this boundary hydrates.
    const ui = moduleOf("overwatch");
    loadDisciplineUI.mockResolvedValue(ui);
    const page = (
      <NextIntlClientProvider locale="en" messages={en}>
        <DisciplineWidget
          discipline="overwatch"
          slot="nativeRankEditor"
          capabilities={NONE}
          props={EDITOR_PROPS}
          fallback={<p>generic</p>}
        />
      </NextIntlClientProvider>
    );
    const container = document.createElement("div");
    container.innerHTML = renderToString(page);
    document.body.appendChild(container);
    peekDisciplineUI.mockReturnValue(ui);

    const onRecoverableError = vi.fn();
    await act(async () => {
      mounted.push({ root: hydrateRoot(container, page, { onRecoverableError }), container });
    });
    await settle();

    expect(onRecoverableError).not.toHaveBeenCalled();
    expect(container.querySelector("[data-slot]")?.textContent).toBe("overwatch editor");
  });
});
