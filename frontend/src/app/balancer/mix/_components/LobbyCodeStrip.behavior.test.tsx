// @vitest-environment happy-dom
//
// The lobby's join code: a host's inline edit stores it trimmed and a blank one clears it; a reader sees the code, or
// nothing without one.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LobbyCodeStrip } from "./LobbyCodeStrip";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

let root: Root | null = null;
let host: HTMLDivElement | null = null;

function render(props: Partial<Parameters<typeof LobbyCodeStrip>[0]> = {}) {
  const onLobbyCodeChange = vi.fn().mockResolvedValue(undefined);
  host ??= document.body.appendChild(document.createElement("div"));
  root ??= createRoot(host);
  act(() =>
    root!.render(
      <LobbyCodeStrip lobbyCode={null} canWrite onLobbyCodeChange={onLobbyCodeChange} {...props} />
    )
  );
  return onLobbyCodeChange;
}

const button = (label: string) => host!.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;

async function save(value: string) {
  await act(async () => button("edit").click());
  const input = host!.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("save").click());
}

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("LobbyCodeStrip", () => {
  it("saves the code trimmed, and a blank field clears it", async () => {
    const onChange = render({ lobbyCode: "OLD" });
    await save("  ABC 123 ");
    expect(onChange).toHaveBeenLastCalledWith("ABC 123");

    await save("   ");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("shows a reader the code, and nothing while there is none", () => {
    render({ canWrite: false, lobbyCode: null });
    expect(host!.textContent).toBe("");

    render({ canWrite: false, lobbyCode: "ABC123" });
    expect(host!.querySelector("input")).toBeNull();
    expect(host!.textContent).toContain("ABC123");
  });
});
