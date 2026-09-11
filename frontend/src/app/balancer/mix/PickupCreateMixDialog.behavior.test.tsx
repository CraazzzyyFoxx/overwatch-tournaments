// @vitest-environment happy-dom

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dialog } from "@/components/ui/dialog";
import messages from "@/i18n/messages/en.json";
import type { CustomGame } from "@/services/custom-game.service";

import { PickupCreateMixDialog } from "./PickupCreateMixDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function sampleGame(id: number, name: string): CustomGame {
  return {
    id,
    workspace_id: 1,
    host_user_id: 10,
    co_hosts: [],
    host_display_name: "HostGuy#1234",
    name,
    status: "completed",
    settings: {
      points_per_win: null,
      team_names: {},
      role_mask: null,
      balancer_config: null,
      discord_channel_id: null,
      workspace_discord_channel_id: null
    },
    balance_result: null,
    created_at: "2026-01-01T00:00:00Z",
    next_map_id: null,
    roster_shape: null,
    matches_count: 5,
    last_match_at: null
  };
}

const mounts: { root: Root; container: HTMLDivElement }[] = [];

afterEach(() => {
  for (const { root, container } of mounts.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  document.body.innerHTML = "";
});

async function mount(
  games: CustomGame[] = [],
  props: {
    creating?: boolean;
    onCreate?: (name: string, cloneFromGameId: number | null) => Promise<unknown>;
    onClose?: () => void;
  } = {}
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounts.push({ root, container });
  const onCreate = props.onCreate ?? vi.fn().mockResolvedValue(undefined);
  const onClose = props.onClose ?? vi.fn();

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <Dialog open={true}>
          <PickupCreateMixDialog
            games={games}
            creating={props.creating ?? false}
            onCreate={onCreate}
            onClose={onClose}
          />
        </Dialog>
      </NextIntlClientProvider>
    );
  });
  return { scope: document.body, onCreate, onClose };
}

const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function submit(scope: HTMLElement) {
  const form = scope.querySelector("form");
  if (!form) throw new Error("Expected a form");
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("PickupCreateMixDialog", () => {
  it("prevents submission when the name is blank and focuses the input", async () => {
    const { scope, onCreate } = await mount([]);
    const input = scope.querySelector('input[name="name"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    await typeInto(input, "   ");
    await submit(scope);

    expect(onCreate).not.toHaveBeenCalled();
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(scope.textContent).toContain("Enter a name for the mix.");
  });

  it("submits valid name and empty lineup by default, closing on success", async () => {
    const { scope, onCreate, onClose } = await mount([]);
    const input = scope.querySelector('input[name="name"]') as HTMLInputElement;

    await typeInto(input, "Friday Scrim");
    await submit(scope);

    expect(onCreate).toHaveBeenCalledWith("Friday Scrim", null);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("requires choosing a source mix if 'From a previous mix' is selected", async () => {
    const game = sampleGame(12, "Old Scrim");
    const { scope, onCreate } = await mount([game]);

    const radios = scope.querySelectorAll('input[type="radio"]');
    expect(radios.length).toBe(2);

    await act(async () => {
      radios[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    await submit(scope);

    expect(onCreate).not.toHaveBeenCalled();
    expect(scope.textContent).toContain("Choose a previous mix.");
  });

  it("keeps entered data and displays error when submission fails", async () => {
    const onCreate = vi.fn().mockRejectedValue(new Error("Network exploded"));
    const { scope, onClose } = await mount([], { onCreate });
    const input = scope.querySelector('input[name="name"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    await typeInto(input, "Kept Name");
    await submit(scope);

    expect(onCreate).toHaveBeenCalledWith("Kept Name", null);
    expect(onClose).not.toHaveBeenCalled();
    const keptInput = scope.querySelector('input[name="name"]') as HTMLInputElement;
    expect(keptInput.value).toBe("Kept Name");
    expect(scope.textContent).toContain("Network exploded");
  });
});
