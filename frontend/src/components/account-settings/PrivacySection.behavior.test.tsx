// @vitest-environment happy-dom
// The stream-privacy switch is a veto, and the two errors that would make it
// lie are cheap to make: reading a missing flag as "hidden" (so the switch
// shows OFF for everyone whose cached profile predates the field), and sending
// the CURRENT value instead of the inverse (so a click either does nothing or
// re-publishes the stream it was meant to hide). Both are pinned here against
// the real component, radix switch included.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PrivacySection from "@/components/account-settings/PrivacySection";
import type { User } from "@/types/user.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getSocialAccounts = vi.fn();
const setStreamVisibility = vi.fn();

vi.mock("@/services/me.service", () => ({
  default: {
    getSocialAccounts: (...args: unknown[]) => getSocialAccounts(...args),
    setStreamVisibility: (...args: unknown[]) => setStreamVisibility(...args),
  },
}));

// Labels come through as their message keys, so the assertions read as the
// keys the component is contracted to use.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canUseCapability: () => true }) }));
// A Next server action; importing the real module explodes outside Next.
vi.mock("@/app/actions/users", () => ({ revalidateUser: vi.fn() }));

function user(overrides: Partial<User>): User {
  return { id: 7, name: "tester", avatar_url: null, social_accounts: [], ...overrides } as User;
}

async function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  await act(async () => {
    await promise;
  });
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <PrivacySection />
      </QueryClientProvider>
    );
  });
  await tick();
  await tick();
  return container;
}

function streamSwitch(container: HTMLElement): HTMLButtonElement {
  const found = container.querySelector<HTMLButtonElement>(
    '[role="switch"][aria-labelledby="stream-visibility-label"]'
  );
  expect(found, "stream-privacy switch").toBeTruthy();
  return found!;
}

beforeEach(() => {
  document.body.innerHTML = "";
  getSocialAccounts.mockReset();
  setStreamVisibility.mockReset();
  setStreamVisibility.mockImplementation((visible: boolean) =>
    Promise.resolve(user({ stream_visible: visible }))
  );
});

describe("PrivacySection stream privacy", () => {
  it("reads a missing stream_visible as allowed and hides the stream on toggle", async () => {
    getSocialAccounts.mockResolvedValue(user({}));
    const container = await mount();

    const toggle = streamSwitch(container);
    expect(toggle.getAttribute("aria-checked")).toBe("true");

    await act(async () => {
      toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await tick();

    expect(setStreamVisibility).toHaveBeenCalledWith(false);
  });

  it("reads stream_visible=false as vetoed and re-allows the stream on toggle", async () => {
    getSocialAccounts.mockResolvedValue(user({ stream_visible: false }));
    const container = await mount();

    const toggle = streamSwitch(container);
    expect(toggle.getAttribute("aria-checked")).toBe("false");

    await act(async () => {
      toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await tick();

    expect(setStreamVisibility).toHaveBeenCalledWith(true);
  });

  it("describes the switch so it is not confused with the per-account visibility toggle", async () => {
    getSocialAccounts.mockResolvedValue(user({}));
    const container = await mount();

    const toggle = streamSwitch(container);
    expect(toggle.getAttribute("aria-describedby")).toBe("stream-visibility-desc");
    expect(container.querySelector("#stream-visibility-label")?.textContent).toBeTruthy();
    expect(container.querySelector("#stream-visibility-desc")?.textContent).toBeTruthy();
  });

  it("stays inert until the current value has actually loaded", async () => {
    // A switch acting on an unloaded value would invert a guess.
    getSocialAccounts.mockReturnValue(Promise.withResolvers<User>().promise);
    const container = await mount();

    expect(streamSwitch(container).disabled).toBe(true);
  });
});
