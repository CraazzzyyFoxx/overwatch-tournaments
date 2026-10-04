// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { AuthMergePolicy, UserMergePreviewRequest, UserMergePreviewResponse } from "@/types/admin.types";
import type { MinimizedUser, User } from "@/types/user.types";
import { UserMergeDialog } from "./UserMergeDialog";

for (const [name, value] of Object.entries({
  hasPointerCapture: () => false,
  setPointerCapture: () => undefined,
  releasePointerCapture: () => undefined,
  scrollIntoView: () => undefined
})) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, { value, writable: true });
  }
}

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { previewMerge, executeMerge, fetchMe } = vi.hoisted(() => ({
  previewMerge: vi.fn(),
  executeMerge: vi.fn(),
  fetchMe: vi.fn()
}));
vi.mock("@/services/admin.service", () => ({
  default: { previewUserMerge: previewMerge, executeUserMerge: executeMerge }
}));
vi.mock("@/stores/auth-profile.store", () => ({
  useAuthProfileStore: { getState: () => ({ fetchMe }) }
}));
vi.mock("@/components/admin/UserSearchCombobox", () => ({
  UserSearchCombobox: ({ id, value, onSelect }: {
    id: string;
    value?: number;
    onSelect: (user: MinimizedUser | undefined) => void;
  }) => (
    <select id={id} value={value ?? ""} onChange={(event) => {
      const nextId = Number(event.target.value);
      onSelect(nextId ? { id: nextId, name: `Target ${nextId}` } : undefined);
    }}>
      <option value="">Choose target</option>
      <option value="2">Target 2</option>
      <option value="3">Target 3</option>
    </select>
  )
}));

const source: User = {
  id: 1,
  name: "Source",
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  avatar_url: null,
  social_accounts: []
};

function policy(overrides: Partial<AuthMergePolicy> = {}): AuthMergePolicy {
  return {
    surviving_auth_user_id: 22,
    other_account_action: "keep",
    oauth_destinations: [{ connection_id: 101, auth_user_id: 11 }],
    conflict_choices: {},
    ...overrides
  };
}

function preview(targetId = 2, authPolicy: AuthMergePolicy | null = policy()): UserMergePreviewResponse {
  return {
    source: {
      id: 1, name: "Source", avatar_url: null, auth_links: authPolicy ? 1 : 0,
      auth_user_id: authPolicy ? 11 : null,
      social_accounts: [{ id: 201, provider: "discord", value: "source-social", duplicate_on_target: false }]
    },
    target: {
      id: targetId, name: `Target ${targetId}`, avatar_url: null, social_accounts: [],
      auth_links: authPolicy ? 1 : 0, auth_user_id: authPolicy ? 22 : null
    },
    conflicts: { has_auth_conflict: false, summary: null },
    affected_counts: { "tournament.player.workspace_member_id": 4 },
    field_options: { name: { source: "Source", target: `Target ${targetId}` }, avatar_url: { source: null, target: null } },
    preview_fingerprint: `reviewed-${targetId}-${JSON.stringify(authPolicy)}`,
    auth_merge: authPolicy ? {
      accounts: [
        { id: 11, username: "incoming-auth", email: "incoming@example.com", has_password: true, is_active: true, is_superuser: false,
          roles: [{ id: 1, name: "member", workspace_id: 7 }],
          denies: [{ permission_id: 8, workspace_id: 7, resource: "users", action: "delete", reason: "restricted" }] },
        { id: 22, username: "existing-auth", email: "existing@example.com", has_password: true, is_active: true, is_superuser: false, roles: [], denies: [] }
      ],
      oauth_connections: [{ id: 101, provider: "discord", provider_user_id: "subject-101", username: "incoming-login", auth_user_id: 11 }],
      policy: authPolicy,
      resource_counts: authPolicy.other_account_action === "delete" ? { favorites: 2 } : {},
      data_conflicts: [],
      permission_changes: authPolicy.other_account_action === "delete",
      issues: [],
      state_fingerprint: "auth-state"
    } : null
  };
}

let root: Root;
let container: HTMLDivElement;
let client: QueryClient;

beforeEach(() => {
  vi.clearAllMocks();
  previewMerge.mockImplementation((request: UserMergePreviewRequest) =>
    Promise.resolve(preview(request.target_user_id, request.auth_policy ?? policy()))
  );
  executeMerge.mockResolvedValue({ surviving_target_user_id: 2 });
  fetchMe.mockResolvedValue(undefined);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
  document.body.innerHTML = "";
});

async function render(open = true, sourceUser = source) {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={en}>
      <UserMergeDialog sourceUser={sourceUser} open={open} onOpenChange={() => {}} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  ));
}

function button(text: string): HTMLButtonElement {
  const found = Array.from(document.body.querySelectorAll("button")).find((item) => item.textContent?.trim() === text);
  if (!found) throw new Error(`Missing button: ${text}`);
  return found;
}

function labelledControl<T extends HTMLElement>(text: string): T {
  const label = Array.from(document.body.querySelectorAll("label")).find((item) => item.textContent?.includes(text));
  const element = label ? document.getElementById(label.htmlFor) : undefined;
  if (!element) throw new Error(`Missing labelled control: ${text}`);
  return element as T;
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click();
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

async function choose(text: string, value: string) {
  const element = labelledControl<HTMLSelectElement>(text);
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

/** Radix Select: opens on pointerdown, listbox is portalled to the document. */
async function openSelect(text: string) {
  const trigger = labelledControl(text);
  await act(async () => {
    trigger.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function option(label: string): HTMLElement {
  const found = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(
    (item) => (item.textContent ?? "").trim() === label
  );
  if (!found) throw new Error(`Missing option: ${label}`);
  return found;
}

async function selectOption(label: string) {
  const item = option(label);
  await act(async () => {
    item.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    item.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function pick(text: string, label: string) {
  await openSelect(text);
  await selectOption(label);
}

async function prepare() {
  await render();
  await choose("Target", "2");
  await click(button("Preview merge"));
}

async function acknowledge(text: string) {
  await click(labelledControl<HTMLButtonElement>(text));
}

describe("profile/auth merge review boundaries", () => {
  it("requires a new preview and independent deletion and permission acknowledgements", async () => {
    await prepare();
    await acknowledge("I reviewed the OAuth destinations");
    await acknowledge("I understand that Source");
    await pick("Other account:", "Delete account and transfer its resources");
    expect(labelledControl<HTMLButtonElement>("I reviewed the OAuth destinations").getAttribute("aria-checked")).toBe("false");
    expect(labelledControl("discord: incoming-login").textContent).toBe("Choose a retained sign-in account");
    await openSelect("discord: incoming-login");
    expect(option("incoming-auth (#11) — selected for deletion").getAttribute("aria-disabled")).toBe("true");
    await selectOption("existing-auth (#22)");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Run “Preview merge” for the current account choices");
    const previewButtons = Array.from(document.body.querySelectorAll("button")).filter((item) => item.textContent?.trim() === "Preview merge");
    expect(previewButtons).toHaveLength(2);
    await click(previewButtons[1]);
    await acknowledge("I reviewed the OAuth destinations");
    await acknowledge("I understand that Source");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
    await acknowledge("I separately confirm permanent deletion");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
    await acknowledge("roles and explicit denies");
    await click(button("Merge and delete source"));
    expect(executeMerge).toHaveBeenCalledTimes(1);
    expect(executeMerge.mock.calls[0][0]).toMatchObject({
      auth_policy: { surviving_auth_user_id: 22, other_account_action: "delete", oauth_destinations: [{ connection_id: 101, auth_user_id: 22 }] },
      confirm_auth_changes: true, confirm_auth_deletion: true, confirm_permission_changes: true
    });
  });

  it("does not use a delayed preview after changing policy, target or dialog lifecycle", async () => {
    await prepare();
    const stalePolicy = Promise.withResolvers<UserMergePreviewResponse>();
    previewMerge.mockReturnValueOnce(stalePolicy.promise);
    await click(button("Preview merge"));
    await pick("Surviving player owner", "incoming-auth (#11)");
    await act(async () => stalePolicy.resolve(preview(2)));
    expect(labelledControl("Surviving player owner").textContent).toBe("incoming-auth (#11)");
    expect(labelledControl<HTMLButtonElement>("I reviewed the OAuth destinations").disabled).toBe(true);
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();

    const staleTarget = Promise.withResolvers<UserMergePreviewResponse>();
    previewMerge.mockReturnValueOnce(staleTarget.promise);
    await click(button("Preview merge"));
    await choose("Target", "3");
    await act(async () => staleTarget.resolve(preview(2, policy({ surviving_auth_user_id: 11 }))));
    expect(document.body.textContent).not.toContain("Sign-in accounts and ownership");

    const staleLifecycle = Promise.withResolvers<UserMergePreviewResponse>();
    previewMerge.mockReturnValueOnce(staleLifecycle.promise);
    await click(button("Preview merge"));
    await render(false);
    await render(true);
    await act(async () => staleLifecycle.resolve(preview(3)));
    expect(labelledControl<HTMLSelectElement>("Target").value).toBe("");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
  });

  it("rejects a preview that returns ownership choices different from the submitted plan", async () => {
    await prepare();
    await pick("Surviving player owner", "incoming-auth (#11)");
    previewMerge.mockResolvedValueOnce(preview(2, policy()));
    await click(button("Preview merge"));
    expect(document.body.textContent).toContain("The preview does not match the submitted account choices");
    expect(labelledControl("Surviving player owner").textContent).toBe("incoming-auth (#11)");
    expect(labelledControl<HTMLButtonElement>("I reviewed the OAuth destinations").disabled).toBe(true);
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
  });

  it("requires reviewed conflict choices instead of treating a draft resolution as approved", async () => {
    previewMerge.mockImplementation((request: UserMergePreviewRequest) => {
      const result = preview(request.target_user_id, request.auth_policy ?? policy());
      result.auth_merge!.data_conflicts = [{ key: "preferences.theme", resource: "preferences", label: "Theme", source_value: "dark", target_value: "light" }];
      result.auth_merge!.issues = request.auth_policy?.conflict_choices["preferences.theme"] ? [] : ["Resolve preference collision"];
      return Promise.resolve(result);
    });
    await prepare();
    expect(document.body.textContent).toContain("Resolve preference collision");
    expect(button("Merge and delete source").disabled).toBe(true);
    await pick("Theme (preferences)", "Incoming");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
    await click(button("Preview merge"));
    await acknowledge("I reviewed the OAuth destinations");
    await acknowledge("I understand that Source");
    await pick("Theme (preferences)", "Existing");
    expect(labelledControl<HTMLButtonElement>("I understand that Source").getAttribute("aria-checked")).toBe("false");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
  });

  it("clears confirmation for profile field and social changes without blocking non-auth merges", async () => {
    previewMerge.mockResolvedValue(preview(2, null));
    await prepare();
    await acknowledge("I understand that Source");
    const nameGroup = Array.from(document.body.querySelectorAll('[role="group"]')).find((group) =>
      group.getAttribute("aria-labelledby") === Array.from(document.body.querySelectorAll("p")).find((item) => item.textContent === "Keep name from")?.id
    );
    await click(nameGroup!.querySelector<HTMLButtonElement>("button")!);
    expect(labelledControl<HTMLButtonElement>("I understand that Source").getAttribute("aria-checked")).toBe("false");
    await click(button("Merge and delete source"));
    expect(executeMerge).not.toHaveBeenCalled();
    await acknowledge("I understand that Source");
    await click(document.body.querySelector<HTMLButtonElement>('[aria-label="Move the Discord identity source-social to the target profile"]')!);
    expect(labelledControl<HTMLButtonElement>("I understand that Source").getAttribute("aria-checked")).toBe("false");
    await acknowledge("I understand that Source");
    await click(button("Merge and delete source"));
    expect(executeMerge).toHaveBeenCalledTimes(1);
    expect(executeMerge.mock.calls[0][0]).toMatchObject({ field_policy: { name: "source" }, identity_selection: { social_account_ids: [] } });
  });
});
