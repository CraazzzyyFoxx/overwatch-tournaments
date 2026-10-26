// @vitest-environment happy-dom
// Deleting the account is re-authenticated server-side: a password account
// sends its current password, a passwordless one needs a recent sign-in (403
// `reauth_required`). Pinned here: the password reaches the request, a wrong one
// is answered in the dialog (not by signing the user out), and a stale sign-in
// offers the regular login dialog that lands back on the security tab.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DeleteAccountSection from "@/components/account-settings/DeleteAccountSection";
import { ApiError } from "@/lib/api/error";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useAuthProfileStore, type AuthProfile } from "@/stores/auth-profile.store";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const deleteAccount = vi.fn();
const logout = vi.fn();

vi.mock("@/services/me.service", () => ({
  default: { deleteAccount: (...args: unknown[]) => deleteAccount(...args) }
}));
vi.mock("@/lib/auth/logout", () => ({ logout: () => logout() }));
// Labels come through as their message keys.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

let root: Root;
let container: HTMLElement;

async function mount(hasPassword: boolean) {
  const user: AuthProfile = {
    id: 7,
    username: "tester",
    roles: [],
    permissions: [],
    denies: [],
    isSuperuser: false,
    hasPassword,
    workspaces: [],
    linkedPlayers: []
  };
  useAuthProfileStore.setState({ status: "authenticated", user });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <DeleteAccountSection />
      </QueryClientProvider>
    );
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (candidate) => candidate.textContent?.trim() === label
  );
  expect(found, `button ${label}`).toBeTruthy();
  return found!;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function dialog(): HTMLElement | null {
  return document.querySelector<HTMLElement>("[role='alertdialog']");
}

beforeEach(() => {
  deleteAccount.mockReset();
  logout.mockReset();
  useAuthModalStore.setState({ isOpen: false, nextPath: "/" });
  useAccountSettingsModalStore.setState({ isOpen: true, activeTab: "security" });
  window.history.replaceState({}, "", "/tournaments");
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("DeleteAccountSection", () => {
  it("asks a password account for its current password and sends it", async () => {
    deleteAccount.mockResolvedValue(undefined);
    await mount(true);
    await click(button("delete"));

    const confirm = button("confirmDelete");
    expect(confirm.disabled).toBe(true);
    await type(dialog()!.querySelector<HTMLInputElement>("input[type='password']")!, "hunter22");
    expect(confirm.disabled).toBe(false);
    await click(confirm);

    expect(deleteAccount).toHaveBeenCalledWith("hunter22");
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("answers a wrong password inside the dialog instead of signing out", async () => {
    deleteAccount.mockRejectedValue(
      new ApiError(401, [{ msg: "Current password is incorrect", code: "unauthorized" }])
    );
    await mount(true);
    await click(button("delete"));
    await type(dialog()!.querySelector<HTMLInputElement>("input[type='password']")!, "wrong");
    await click(button("confirmDelete"));

    expect(dialog()?.querySelector("[role='alert']")?.textContent).toBe("wrongPassword");
    expect(logout).not.toHaveBeenCalled();
  });

  it("offers a fresh sign-in back to the security tab when the session is too old", async () => {
    deleteAccount.mockRejectedValue(
      new ApiError(403, [{ msg: "reauth_required", code: "forbidden" }])
    );
    await mount(false);
    await click(button("delete"));

    // A passwordless account has nothing to type.
    expect(dialog()?.querySelector("input[type='password']")).toBeNull();
    await click(button("confirmDelete"));

    expect(deleteAccount).toHaveBeenCalledWith(undefined);
    expect(dialog()?.textContent).toContain("reauthRequired");
    expect(button("confirmDelete").disabled).toBe(true);

    await click(button("signInAgain"));

    expect(useAccountSettingsModalStore.getState().isOpen).toBe(false);
    expect(useAuthModalStore.getState()).toMatchObject({
      isOpen: true,
      nextPath: "/tournaments?settings=security"
    });
    expect(logout).not.toHaveBeenCalled();
  });
});
