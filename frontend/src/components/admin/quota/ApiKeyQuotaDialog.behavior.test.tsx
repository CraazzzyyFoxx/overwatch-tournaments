// @vitest-environment happy-dom
//
// The two things this dialog has to get right are both about attribution.
//
// A quota refusal names exactly ONE of the two budgets a key spends from, so
// the dialog is useless unless both are on screen and labelled: a 429 on a key
// sitting at 2/600 requests is the workspace pool running dry, and without the
// workspace bar next to the key bar that reads as a random failure.
//
// And a write refused with 422 `quota_above_inherited` names exactly ONE of the
// five numbers. It has to land on that input — a toast saying "could not save"
// leaves the admin re-typing all five to find out which one the server hated.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { AccountApiKey, QuotaScope, QuotaScopeUsage } from "@/types/auth.types";

import { ApiKeyQuotaDialog } from "./ApiKeyQuotaDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

const notifySuccess = vi.fn();
const notifyApiError = vi.fn();
vi.mock("@/lib/notify", () => ({
  notify: {
    success: (...args: unknown[]) => notifySuccess(...args),
    apiError: (...args: unknown[]) => notifyApiError(...args),
    error: vi.fn(),
    warning: vi.fn()
  }
}));

const API_KEY: AccountApiKey = {
  id: 7,
  name: "bulk importer",
  workspace_id: 42,
  public_id: "abc123",
  owner_id: 1,
  owner_username: "operator",
  scopes: ["log.create"],
  created_at: "2026-01-01T00:00:00Z"
};

function scope(name: QuotaScope, over: Partial<QuotaScopeUsage> = {}): QuotaScopeUsage {
  return {
    scope: name,
    requests_per_minute: 600,
    requests_used: 2,
    requests_reset_in: 40,
    heavy_per_day: 500,
    heavy_used: 10,
    heavy_reset_in: 3600,
    concurrent_heavy: 4,
    concurrent_used: 0,
    max_upload_bytes: 10 * 1024 * 1024,
    max_items_per_request: 500,
    ...over
  };
}

const fetchMock = vi.fn();

async function settle() {
  for (let i = 0; i < 20; i += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <ApiKeyQuotaDialog apiKey={API_KEY} workspaceId={42} onClose={vi.fn()} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  // Radix portals the dialog out of `container`, so the assertions read the
  // document, not the mount node.
  return document.body;
}

function field(dimension: string): HTMLInputElement {
  const found = [...document.body.querySelectorAll("input")].find((el) =>
    el.id.endsWith(`-${dimension}`)
  );
  if (!found) throw new Error(`no input for ${dimension}`);
  return found as HTMLInputElement;
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  const form = document.body.querySelector("form");
  if (!form) throw new Error("no form");
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

beforeEach(() => {
  document.body.innerHTML = "";
  notifySuccess.mockReset();
  notifyApiError.mockReset();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      plan_slug: "verified",
      workspace_id: 42,
      scopes: [scope("key"), scope("workspace", { requests_used: 598, heavy_used: 500 })]
    })
  });
  vi.stubGlobal("fetch", fetchMock);
});

describe("ApiKeyQuotaDialog", () => {
  it("names both budgets the key spends from, so a refusal can be attributed", async () => {
    const body = await mount();

    expect(body.textContent).toContain(en.quota.scopes.key.label);
    expect(body.textContent).toContain(en.quota.scopes.workspace.label);
    // The distinction the screen exists for: this key is nearly idle while the
    // workspace pool is spent.
    expect(body.textContent).toContain("2 of 600");
    expect(body.textContent).toContain("598 of 600");

    const bars = [...body.querySelectorAll('[role="progressbar"]')];
    const labels = bars.map((bar) => bar.getAttribute("aria-label"));
    expect(labels).toContain(
      `${en.quota.scopes.key.label} — ${en.quota.dimensions.requests_per_minute.label}`
    );
    expect(labels).toContain(
      `${en.quota.scopes.workspace.label} — ${en.quota.dimensions.requests_per_minute.label}`
    );
  });

  it("puts a 422 quota_above_inherited on the field it names, not in a toast", async () => {
    await mount();

    await type(field("heavy_per_day"), "5000");
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        detail: "quota above inherited",
        code: "unprocessable",
        fields: [
          {
            field: null,
            msg: "quota above inherited",
            code: "quota_above_inherited",
            limit_name: "heavy_per_day",
            limit: 500,
            requested: 5000
          }
        ]
      })
    });
    await submit();

    const input = field("heavy_per_day");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const described = (input.getAttribute("aria-describedby") ?? "").split(" ");
    const messages = described
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(messages).toContain("500");
    expect(messages).toContain("5000");
    // The other four numbers are innocent and must not be marked.
    expect(field("requests_per_minute").getAttribute("aria-invalid")).toBeNull();
    expect(notifyApiError).not.toHaveBeenCalled();
  });

  it("falls back to a toast when the failure names no dimension", async () => {
    const body = await mount();

    await type(field("requests_per_minute"), "30");
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Forbidden", code: "forbidden" })
    });
    await submit();

    expect(notifyApiError).toHaveBeenCalled();
    expect(field("requests_per_minute").getAttribute("aria-invalid")).toBeNull();
    expect(body.textContent).toContain(en.quota.overrideHeading);
  });

  it("sends an all-null payload as the way to stop overriding", async () => {
    await mount();
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({}) });
    await submit();

    // A successful write invalidates the usage query, so the LAST call is the
    // refetch; the write is the one carrying a method.
    const write = (fetchMock.mock.calls as [string, RequestInit][]).find(
      ([, init]) => init?.method === "PUT"
    );
    if (!write) throw new Error("no PUT was sent");
    const [url, init] = write;
    expect(url).toBe("/api/account/api-keys/7/quota");
    expect(JSON.parse(init.body as string)).toEqual({
      limits: {
        requests_per_minute: null,
        heavy_per_day: null,
        concurrent_heavy: null,
        max_upload_bytes: null,
        max_items_per_request: null
      }
    });
  });
});
