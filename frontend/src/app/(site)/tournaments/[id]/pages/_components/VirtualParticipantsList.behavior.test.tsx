import { afterAll, afterEach, beforeAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act, useState, type ReactNode } from "react";
import type { Root } from "react-dom/client";

import type { Registration } from "@/types/registration.types";

import type { ColumnDefinition } from "./participantsColumns";
import { readParticipantUrlState } from "./participants-url-state";

const testWindow = new Window({
  url: "http://localhost:3000/tournaments/72/participants",
  width: 1280,
  height: 900
});
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();
const mountedRoots = new Set<Root>();

class TestResizeObserver {
  static readonly instances = new Set<TestResizeObserver>();

  readonly callback: ResizeObserverCallback;
  readonly targets = new Set<Element>();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    TestResizeObserver.instances.add(this);
  }

  private emit(target: Element) {
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

  observe(target: Element) {
    this.targets.add(target);
  }

  disconnect() {
    this.targets.clear();
    TestResizeObserver.instances.delete(this);
  }

  unobserve(target: Element) {
    this.targets.delete(target);
  }

  static notify(target: Element) {
    for (const observer of TestResizeObserver.instances) {
      if (observer.targets.has(target)) observer.emit(target);
    }
  }
}

const originalWindowResizeObserver = Object.getOwnPropertyDescriptor(
  testWindow,
  "ResizeObserver"
);

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key
}));
mock.module("@/components/BattleTagRankHistory", () => ({
  default: () => <div data-rank-history="true" />
}));
mock.module("@/components/ui/checkbox", () => ({
  Checkbox: ({
    checked,
    disabled,
    onCheckedChange
  }: {
    checked?: boolean;
    disabled?: boolean;
    onCheckedChange?: (checked: boolean) => void;
  }) => (
    <button
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange?.(!checked)}
      role="checkbox"
      type="button"
    />
  )
}));
mock.module("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PopoverContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => <>{children}</>
}));

let createRoot: typeof import("react-dom/client").createRoot;
let VirtualParticipantsList: typeof import("./VirtualParticipantsList").default;
let ColumnPicker: typeof import("./ColumnPicker").default;

function restoreGlobals() {
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
  previousGlobals.clear();
}

function installGlobals() {
  const values = {
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
  };

  try {
    for (const [key, value] of Object.entries(values)) {
      previousGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, {
        configurable: true,
        value,
        writable: true
      });
    }
  } catch (error) {
    restoreGlobals();
    throw error;
  }
}

function createTestRoot(container: Element) {
  const root = createRoot(container);
  mountedRoots.add(root);
  return root;
}

const originalBoundingRect = testWindow.HTMLElement.prototype.getBoundingClientRect;
const originalOffsetHeight = Object.getOwnPropertyDescriptor(
  testWindow.HTMLElement.prototype,
  "offsetHeight"
);
let listDocumentTop = 0;
let layoutBoundaryHeight = 1200;

function elementHeight(element: Element): number {
  if (element.hasAttribute("data-index")) {
    return element.getAttribute("data-expanded") === "true" ? 204 : 68;
  }
  if (element.hasAttribute("data-participant-layout")) return layoutBoundaryHeight;
  return 0;
}

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
const statusColumn: ColumnDefinition = {
  id: "_status",
  label: "Status",
  category: "meta",
  defaultVisible: true,
  render: (row) => <span data-registration-status={row.id}>{row.status}</span>
};
const heavyColumn: ColumnDefinition = {
  id: "notes",
  label: "Notes",
  category: "built_in",
  defaultVisible: false,
  render: (row) => <span data-heavy-detail={row.id}>{row.notes ?? "No notes"}</span>
};

function ExpandableListHarness() {
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<number>>(new Set());

  return (
    <VirtualParticipantsList
      allColumns={[imageColumn, statusColumn, heavyColumn]}
      expandedIds={expandedIds}
      onToggleExpanded={(registrationId) =>
        setExpandedIds((current) => {
          const next = new Set(current);
          if (next.has(registrationId)) next.delete(registrationId);
          else next.add(registrationId);
          return next;
        })
      }
      registrations={[registration(1)]}
      visibleColumns={[imageColumn, statusColumn]}
    />
  );
}

beforeAll(async () => {
  installGlobals();
  Object.defineProperty(testWindow, "ResizeObserver", {
    configurable: true,
    value: TestResizeObserver,
    writable: true
  });
  Object.defineProperty(testWindow.HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return elementHeight(this);
    }
  });
  testWindow.HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
    const height = elementHeight(this);
    const isListStart =
      this.parentElement?.getAttribute("role") === "table" &&
      this.getAttribute("role") === null;
    const top = isListStart ? listDocumentTop - window.scrollY : 0;
    return {
      x: 0,
      y: top,
      top,
      left: 0,
      width: 1280,
      height,
      right: 1280,
      bottom: top + height,
      toJSON: () => ({})
    } as DOMRect;
  };
  ({ createRoot } = await import("react-dom/client"));
  ({ default: VirtualParticipantsList } = await import("./VirtualParticipantsList"));
  ({ default: ColumnPicker } = await import("./ColumnPicker"));
});

afterEach(() => {
  try {
    act(() => {
      for (const root of mountedRoots) root.unmount();
    });
  } finally {
    mountedRoots.clear();
    for (const observer of [...TestResizeObserver.instances]) observer.disconnect();
    document.body.replaceChildren();
    listDocumentTop = 0;
    layoutBoundaryHeight = 1200;
    Object.defineProperty(testWindow, "scrollY", {
      configurable: true,
      value: 0,
      writable: true
    });
  }
});

afterAll(async () => {
  try {
    testWindow.HTMLElement.prototype.getBoundingClientRect = originalBoundingRect;
    if (originalOffsetHeight) {
      Object.defineProperty(testWindow.HTMLElement.prototype, "offsetHeight", originalOffsetHeight);
    }
    if (originalWindowResizeObserver) {
      Object.defineProperty(testWindow, "ResizeObserver", originalWindowResizeObserver);
    } else {
      Reflect.deleteProperty(testWindow, "ResizeObserver");
    }
    mock.restore();
    await testWindow.close();
  } finally {
    restoreGlobals();
  }
});

describe("VirtualParticipantsList mount budget", () => {
  it("renders a bounded window for 500 registrations without far-row images", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

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

  });

  it("mounts expensive details only for the expanded row and remeasures its height", async () => {
    const container = document.createElement("div");
    container.setAttribute("data-participant-layout", "true");
    document.body.append(container);
    const root = createTestRoot(container);

    await act(async () => {
      root.render(<ExpandableListHarness />);
      await new Promise<void>((resolve) => testWindow.requestAnimationFrame(() => resolve()));
    });

    const row = container.querySelector<HTMLElement>("[data-index]")!;
    const spacer = row.parentElement as HTMLElement;
    const initialHeight = Number.parseFloat(spacer.style.height);
    const expander = row.querySelector<HTMLButtonElement>("button[aria-controls]")!;
    const detailsId = expander.getAttribute("aria-controls")!;
    const table = container.querySelector<HTMLElement>('[role="table"]')!;
    const summaryRow = row.querySelector<HTMLElement>('[role="row"]')!;

    expect(table.getAttribute("aria-rowcount")).toBe("2");
    expect(table.querySelectorAll('[role="row"]')).toHaveLength(2);
    expect(row.getAttribute("role")).toBeNull();
    expect(row.getAttribute("aria-rowindex")).toBeNull();
    expect(summaryRow.getAttribute("aria-rowindex")).toBe("2");
    expect(summaryRow.querySelectorAll(':scope > [role="cell"]')).toHaveLength(3);
    expect(container.querySelectorAll("[data-rank-history]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-heavy-detail]")).toHaveLength(0);
    expect(container.querySelector(`#${detailsId}`)).toBeNull();

    expander.focus();
    act(() => expander.click());
    await act(async () => TestResizeObserver.notify(row));

    const region = container.querySelector<HTMLElement>(`#${detailsId}`)!;
    expect(container.querySelectorAll("[data-rank-history]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-heavy-detail]")).toHaveLength(1);
    expect(region.getAttribute("role")).toBe("region");
    expect(region.closest('[role="row"]')).toBeNull();
    expect(region.parentElement?.getAttribute("role")).toBeNull();
    expect(region.parentElement?.getAttribute("aria-colspan")).toBeNull();
    expect(summaryRow.querySelectorAll(':scope > [role="cell"]')).toHaveLength(3);
    expect(Number.parseFloat(spacer.style.height)).toBeGreaterThan(initialHeight);

    const collapseButton = row.querySelector<HTMLButtonElement>("button[aria-controls]")!;
    act(() => collapseButton.click());
    await act(async () => TestResizeObserver.notify(row));

    expect(container.querySelectorAll("[data-rank-history]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-heavy-detail]")).toHaveLength(0);
    expect(container.querySelector(`#${detailsId}`)).toBeNull();
    expect(document.activeElement).toBe(collapseButton);
    expect(Number.parseFloat(spacer.style.height)).toBe(initialHeight);

  });

  it("keeps identity and status in the same row DOM when URL columns are none", async () => {
    const selected = readParticipantUrlState(
      new URLSearchParams("participantColumns=none"),
      ["approved"],
      [imageColumn, heavyColumn, statusColumn]
    ).state.visibleColumnIds;
    const columns = [imageColumn, heavyColumn, statusColumn];
    const visibleColumns = columns.filter((column) => selected.includes(column.id));
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

    await act(async () => {
      root.render(
        <VirtualParticipantsList
          allColumns={columns}
          expandedIds={new Set()}
          onToggleExpanded={() => {}}
          registrations={[registration(1)]}
          visibleColumns={visibleColumns}
        />
      );
      await new Promise<void>((resolve) => testWindow.requestAnimationFrame(() => resolve()));
    });

    const row = container.querySelector<HTMLElement>("[data-index]")!;
    expect(row.querySelectorAll('[data-participant-kind="identity"]')).toHaveLength(1);
    expect(row.querySelectorAll('[data-participant-kind="status"]')).toHaveLength(1);
    expect(row.querySelector('[data-column-id="notes"]')).toBeNull();

  });

  it("locks mandatory identity and status controls in the column picker", () => {
    const toggled: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

    act(() => {
      root.render(
        <ColumnPicker
          columns={[imageColumn, statusColumn, heavyColumn]}
          onReset={() => {}}
          onToggle={(id) => toggled.push(id)}
          visibility={{ battle_tag: true, _status: true, notes: false }}
        />
      );
    });

    const labels = Array.from(container.querySelectorAll("label"));
    const identityToggle = labels
      .find((label) => label.textContent?.includes("Player"))!
      .querySelector<HTMLButtonElement>('[role="checkbox"]')!;
    const statusToggle = labels
      .find((label) => label.textContent?.includes("Status"))!
      .querySelector<HTMLButtonElement>('[role="checkbox"]')!;
    const notesToggle = labels
      .find((label) => label.textContent?.includes("Notes"))!
      .querySelector<HTMLButtonElement>('[role="checkbox"]')!;

    expect(identityToggle.disabled).toBe(true);
    expect(statusToggle.disabled).toBe(true);
    identityToggle.click();
    statusToggle.click();
    expect(toggled).toEqual([]);
    expect(notesToggle.disabled).toBe(false);
    notesToggle.click();
    expect(toggled).toEqual(["notes"]);

  });

  it("remeasures the document margin when a preceding layout shift moves the list", async () => {
    Object.defineProperty(testWindow, "scrollY", {
      configurable: true,
      value: 2000,
      writable: true
    });
    listDocumentTop = 120;
    const container = document.createElement("div");
    container.setAttribute("data-participant-layout", "true");
    document.body.append(container);
    const root = createTestRoot(container);

    await act(async () => {
      root.render(
        <VirtualParticipantsList
          allColumns={[imageColumn, statusColumn]}
          expandedIds={new Set()}
          onToggleExpanded={() => {}}
          registrations={registrations}
          visibleColumns={[imageColumn, statusColumn]}
        />
      );
      await new Promise<void>((resolve) => testWindow.requestAnimationFrame(() => resolve()));
    });

    const firstIndexBefore = Number(
      container.querySelector<HTMLElement>("[data-index]")!.dataset.index
    );
    listDocumentTop = 520;
    layoutBoundaryHeight = 1600;
    TestResizeObserver.notify(container);
    await act(async () => {
      await new Promise<void>((resolve) => testWindow.requestAnimationFrame(() => resolve()));
    });

    const rowsAfter = container.querySelectorAll<HTMLElement>("[data-index]");
    const firstRowAfter = rowsAfter[0];
    const firstIndexAfter = Number(firstRowAfter.dataset.index);
    expect(firstIndexAfter).toBeLessThan(firstIndexBefore);
    expect(rowsAfter.length).toBeLessThanOrEqual(40);
    expect(firstRowAfter.style.transform).toBe(
      `translateY(${firstIndexAfter * 68}px)`
    );

  });
});
