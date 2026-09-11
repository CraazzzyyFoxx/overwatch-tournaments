// @vitest-environment happy-dom
//
// The list is where a host picks up the contracts the mix screen's header used
// to own directly:
//
//  1. creating a mix trims the name and refuses an all-whitespace one, because
//     the server would accept it and leave an unnameable row in the list;
//  2. a viewer who cannot host gets no create form;
//  3. every row names its mix, its host, how active it has been and when it
//     was created, and links to the mix screen for that id;
//  4. a new mix defaults to cloning the newest one, and Empty opts out --
//     the popover is the only place that choice is made.
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGame } from "@/services/custom-game.service";

import { PickupMixList } from "./PickupMixList";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
// Radix's Select needs real pointer capture to open, which happy-dom does not
// provide; rendered here as a native <select> so the choice stays testable.
vi.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => (
    <select
      aria-label="Lineup from"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

const onRetry = vi.fn();
const onCreateGame = vi.fn();

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 12,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: "HostTag#1234",
    name: "Thursday scrim",
    status: "balanced",
    balance_result: null,
    created_at: "2026-01-02T00:00:00Z",
    next_map_id: null,
    matches_count: 0,
    last_match_at: null,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

// Roots are unmounted rather than the body cleared: the create form lives in a
// portal, so a stale root and a wiped body raced into `removeChild` failures.
const roots: { unmount: () => void }[] = [];

async function mount(
  games: CustomGame[],
  props: { canEdit?: boolean; loading?: boolean; error?: boolean } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupMixList
        canEdit={props.canEdit ?? true}
        games={games}
        loading={props.loading ?? false}
        error={props.error ?? false}
        onRetry={onRetry}
        creating={false}
        onCreateGame={onCreateGame}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

async function type(input: HTMLInputElement, value: string) {
  // Native setter, not `input.value =`: React's value tracker would otherwise
  // see no change and swallow the event.
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
  });
}

/** happy-dom does not submit a form from a submit-button click. */
async function submit(form: Element | null) {
  if (!form) throw new Error("Expected a form");
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await tick();
  });
}

/** The "Lineup from" picker, rendered as a native <select> by the mock above. */
async function pickSource(value: string) {
  const field = document.querySelector<HTMLSelectElement>('select[aria-label="Lineup from"]');
  if (!field) throw new Error("Expected the lineup source picker");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set?.call(field, value);
    field.dispatchEvent(new Event("change", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  while (roots.length > 0) {
    const root = roots.pop();
    act(() => root?.unmount());
  }
  document.body.innerHTML = "";
  onRetry.mockReset();
  onCreateGame.mockReset();
});

describe("PickupMixList", () => {
  it("names each row with its mix, host and creation date, linking to the mix screen", async () => {
    const scope = await mount([game()]);

    expect(scope.textContent).toContain("Thursday scrim");
    expect(scope.textContent).toContain("#12");
    expect(scope.textContent).toContain("HostTag#1234");

    const link = scope.querySelector('a[href="/balancer/pickup/12"]');
    expect(link).not.toBeNull();
  });

  it("falls back to the raw host id when no display name resolved", async () => {
    const scope = await mount([game({ host_display_name: null })]);

    expect(scope.textContent).toContain("#9");
  });

  it("creates a mix under its trimmed name", async () => {
    const scope = await mount([game()]);

    await click(byName(scope, "New mix"));
    const input = document.querySelector<HTMLInputElement>("#pickup-new-mix");
    expect(input).not.toBeNull();

    await type(input as HTMLInputElement, "  Sunday scrim  ");
    await submit(input?.closest("form") ?? null);

    // The newest mix is the default lineup source, so a plain create clones it.
    expect(onCreateGame).toHaveBeenCalledWith("Sunday scrim", 12);
  });

  it("starts a mix from nothing once the host picks Empty", async () => {
    const scope = await mount([game()]);

    await click(byName(scope, "New mix"));
    await pickSource("empty");
    const input = document.querySelector<HTMLInputElement>("#pickup-new-mix");
    await type(input as HTMLInputElement, "Fresh night");
    await submit(input?.closest("form") ?? null);

    expect(onCreateGame).toHaveBeenCalledWith("Fresh night", null);
  });

  it("names the source mix in the empty name field, but never overwrites the host's own", async () => {
    const scope = await mount([game({ id: 12, name: "Newest" }), game({ id: 4, name: "Older" })]);

    await click(byName(scope, "New mix"));
    await pickSource("4");
    const input = document.querySelector<HTMLInputElement>("#pickup-new-mix");
    expect(input?.value).toBe("Older");

    await type(input as HTMLInputElement, "My own name");
    await pickSource("12");
    expect(input?.value).toBe("My own name");

    await submit(input?.closest("form") ?? null);
    expect(onCreateGame).toHaveBeenCalledWith("My own name", 12);
  });

  it("reports how active a mix has been next to when it was created", async () => {
    const scope = await mount([
      game({ matches_count: 3, last_match_at: "2026-01-03T00:00:00Z" }),
    ]);

    expect(scope.textContent).toContain("3 maps");
  });

  it("reads as inactive while a mix has recorded nothing", async () => {
    const scope = await mount([game()]);

    expect(scope.textContent).toContain("No matches");
  });

  it("refuses a whitespace-only mix name", async () => {
    const scope = await mount([game()]);

    await click(byName(scope, "New mix"));
    await type(document.querySelector<HTMLInputElement>("#pickup-new-mix") as HTMLInputElement, "   ");

    expect(byName(document, "Create")?.hasAttribute("disabled")).toBe(true);
    expect(onCreateGame).not.toHaveBeenCalled();
  });

  it("gives a viewer who cannot host no create form", async () => {
    const scope = await mount([game()], { canEdit: false });

    expect(byName(scope, "New mix")).toBeNull();
    // Reading the list is not a write.
    expect(scope.textContent).toContain("Thursday scrim");
  });

  it("shows an empty state instead of a form when there are no mixes", async () => {
    const scope = await mount([]);

    expect(scope.textContent).toContain("No mixes yet");
  });

  it("offers a retry when the list fails to load", async () => {
    const scope = await mount([], { error: true });

    expect(scope.textContent).toContain("Unable to load mixes");
    await click(byName(scope, "Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
