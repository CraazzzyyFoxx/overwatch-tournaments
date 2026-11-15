// @vitest-environment happy-dom

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dialog } from "@craazzzyyfoxx/admin-kit/ui/dialog";
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
    discipline: "overwatch",
    host_user_id: 10,
    co_hosts: [],
    host_display_name: "HostGuy#1234",
    name,
    status: "completed",
    settings: {
      points_per_win: 0,
      team_names: {},
      workspace_discord_channel_id: null
    },
    created_at: "2026-01-01T00:00:00Z",
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null
      },
    ],
    self_signup: "closed",
    self_role_edit: false,
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
    onCreate?: (
      name: string,
      cloneFromGameId: number | null,
      workspaceId: number,
      discipline: string
    ) => Promise<unknown>;
    onClose?: () => void;
    scopedWorkspaceId?: number | null;
    fixedDiscipline?: string | null;
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
            workspaces={[
              { id: 1, name: "Alpha", disciplines_enabled: ["overwatch", "lol"] },
              { id: 2, name: "Beta", disciplines_enabled: ["overwatch"] }
            ]}
            disciplines={[
              { code: "overwatch", name: "Overwatch" },
              { code: "lol", name: "League of Legends" }
            ]}
            fixedDiscipline={props.fixedDiscipline === undefined ? "overwatch" : props.fixedDiscipline}
            scopedWorkspaceId={props.scopedWorkspaceId === undefined ? 1 : props.scopedWorkspaceId}
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

/** Opens the combobox behind `triggerId` and picks the option labelled `label`. */
async function pick(scope: HTMLElement, triggerId: string, label: string) {
  await act(async () => {
    (scope.querySelector(`#${triggerId}`) as HTMLButtonElement).click();
  });
  const option = [...scope.querySelectorAll<HTMLElement>("[cmdk-item]")].find(
    (node) => node.textContent?.trim() === label
  );
  if (!option) throw new Error(`Expected option ${label}`);
  await act(async () => {
    option.click();
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

    expect(onCreate).toHaveBeenCalledWith("Friday Scrim", null, 1, "overwatch");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("requires choosing a source mix if 'From a previous mix' is selected", async () => {
    const game = sampleGame(12, "Old Scrim");
    const { scope, onCreate } = await mount([game]);

    const radios = scope.querySelectorAll('[role="radio"]');
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

    expect(onCreate).toHaveBeenCalledWith("Kept Name", null, 1, "overwatch");
    expect(onClose).not.toHaveBeenCalled();
    const keptInput = scope.querySelector('input[name="name"]') as HTMLInputElement;
    expect(keptInput.value).toBe("Kept Name");
    expect(scope.textContent).toContain("Network exploded");
  });

  it("requires an explicit community in all mode and offers clones only from that community", async () => {
    const alpha = sampleGame(12, "Alpha mix");
    const beta = { ...sampleGame(13, "Beta mix"), workspace_id: 2 };
    const { scope, onCreate } = await mount([alpha, beta], { scopedWorkspaceId: null });
    await submit(scope);
    expect(onCreate).not.toHaveBeenCalled();
    const trigger = scope.querySelector("#pickup-workspace") as HTMLButtonElement;
    expect(trigger.getAttribute("aria-invalid")).toBe("true");
    await pick(scope, "pickup-workspace", "Beta");
    expect(trigger.getAttribute("aria-invalid")).toBeNull();
    await act(async () => {
      scope.querySelectorAll('[role="radio"]')[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      (scope.querySelector("#pickup-clone-from") as HTMLButtonElement).click();
    });
    expect(scope.textContent).toContain("Beta mix");
    expect(scope.textContent).not.toContain("Alpha mix");
    await pick(scope, "pickup-workspace", "Alpha");
    expect(scope.querySelector("#pickup-clone-from")).toBeNull();
    await submit(scope);
    expect(onCreate).toHaveBeenCalledWith(expect.any(String), null, 1, "overwatch");
  });

  it("names the directory's game and offers no other", async () => {
    const { scope, onCreate } = await mount([], { fixedDiscipline: "lol" });
    expect(scope.querySelector('#pickup-discipline[role="combobox"]')).toBeNull();
    expect(scope.querySelector("#pickup-discipline")?.textContent).toBe("League of Legends");
    await submit(scope);
    expect(onCreate).toHaveBeenCalledWith(expect.any(String), null, 1, "lol");
  });

  it("refuses a directory game the community has not enabled", async () => {
    const { scope, onCreate } = await mount([], { fixedDiscipline: "lol", scopedWorkspaceId: 2 });
    expect(scope.textContent).toContain("This community has not enabled this game.");
    await submit(scope);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("makes the host name the game under all games and copies only from a mix of that game", async () => {
    const owMix = sampleGame(12, "OW mix");
    const lolMix = { ...sampleGame(14, "LoL mix"), discipline: "lol" };
    const { scope, onCreate } = await mount([owMix, lolMix], { fixedDiscipline: null });
    const trigger = scope.querySelector("#pickup-discipline") as HTMLButtonElement;
    expect(trigger.textContent).toBe("Choose a game");
    await act(async () => {
      trigger.click();
    });
    expect([...scope.querySelectorAll("[cmdk-item]")].map((option) => option.textContent)).toEqual([
      "Overwatch",
      "League of Legends"
    ]);
    await act(async () => {
      trigger.click();
    });

    await submit(scope);
    expect(onCreate).not.toHaveBeenCalled();
    expect(trigger.getAttribute("aria-invalid")).toBe("true");
    expect(scope.textContent).toContain("Choose the game this mix is for.");

    await pick(scope, "pickup-discipline", "League of Legends");
    expect(trigger.textContent).toBe("League of Legends");
    await act(async () => {
      scope.querySelectorAll('[role="radio"]')[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      (scope.querySelector("#pickup-clone-from") as HTMLButtonElement).click();
    });
    expect(scope.textContent).toContain("LoL mix");
    expect(scope.textContent).not.toContain("OW mix");
  });
});
