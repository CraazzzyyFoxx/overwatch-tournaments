// @vitest-environment happy-dom
//
// Three things this dialog has to get right.
//
// Attribution: a quota refusal names exactly ONE of the two budgets a key
// spends from, so the dialog is useless unless both are on screen and
// labelled: a 429 on a key sitting at 2/600 requests is the workspace pool
// running dry, and without the workspace bar next to the key bar that reads as
// a random failure. Likewise a write refused with 422 `quota_above_inherited`
// names exactly ONE of the five numbers, and it has to land on that input.
//
// The stored row: the fields are seeded from the override written on the key.
// They used to start blank while the read reported only EFFECTIVE ceilings, so
// the dialog showed nothing about what was stored and its submit sent an
// all-null payload — i.e. opening it and pressing the button deleted limits
// nobody could see.
//
// Authority: raising a limit above what the key inherits is superuser-only, so
// the field says so instead of spending a round trip on a 422 an admin cannot
// act on.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type {
  AccountApiKey,
  QuotaLimitsPayload,
  QuotaScope,
  QuotaScopePolicy,
  QuotaScopeUsage
} from "@/types/auth.types";

import { ApiKeyQuotaDialog } from "./ApiKeyQuotaDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

let superuser = false;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: superuser })
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

const NO_LIMITS: QuotaLimitsPayload = {
  requests_per_minute: null,
  heavy_per_day: null,
  concurrent_heavy: null,
  max_upload_bytes: null,
  max_items_per_request: null
};

/** The key's stored row plus the ceiling `set_quota` holds it to. */
function policy(override: Partial<QuotaLimitsPayload> = {}): QuotaScopePolicy {
  return {
    scope: "key",
    override: { ...NO_LIMITS, heavy_per_day: 120, ...override },
    inherited: {
      requests_per_minute: 600,
      heavy_per_day: 500,
      concurrent_heavy: 4,
      max_upload_bytes: 10 * 1024 * 1024,
      max_items_per_request: 500
    }
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

// React installs a value tracker on controlled inputs, so a plain
// `input.value = x` looks like "no change" and onChange never fires. Going
// through the prototype setter is what makes the keystroke real.
const setInputValue = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype,
  "value"
)!.set!;

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    setInputValue.call(input, value);
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

function respondWith(rows: QuotaScopePolicy[]) {
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      plan_slug: "verified",
      workspace_id: 42,
      scopes: [scope("key"), scope("workspace", { requests_used: 598, heavy_used: 500 })],
      policy: rows
    })
  });
}

/** The PUT the dialog sent, skipping the refetch that follows a success. */
function writtenLimits(): QuotaLimitsPayload {
  const write = (fetchMock.mock.calls as [string, RequestInit][]).find(
    ([, init]) => init?.method === "PUT"
  );
  if (!write) throw new Error("no PUT was sent");
  const [url, init] = write;
  expect(url).toBe("/bff/account/api-keys/7/quota");
  return JSON.parse(init.body as string).limits as QuotaLimitsPayload;
}

beforeEach(() => {
  document.body.innerHTML = "";
  superuser = false;
  notifySuccess.mockReset();
  notifyApiError.mockReset();
  fetchMock.mockReset();
  respondWith([policy()]);
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

  it("starts from the override stored on the key, not from a blank form", async () => {
    await mount();

    // The row says 120 heavy units a day and inherits the rest. A blank form
    // here is not a neutral start: submitting it deletes the row.
    expect(field("heavy_per_day").value).toBe("120");
    expect(field("requests_per_minute").value).toBe("");
    expect(document.body.textContent).toContain(en.quota.state.overridden);

    await submit();
    expect(writtenLimits().heavy_per_day).toBe(120);
  });

  it("empties every field to stop overriding, and says so on the button", async () => {
    await mount();

    await type(field("heavy_per_day"), "");
    const submitButton = [...document.body.querySelectorAll("button")].find((button) =>
      button.textContent?.includes(en.quota.clearOverride)
    );
    expect(submitButton).toBeTruthy();

    await submit();
    expect(writtenLimits()).toEqual({
      requests_per_minute: null,
      heavy_per_day: null,
      concurrent_heavy: null,
      max_upload_bytes: null,
      max_items_per_request: null
    });
  });

  it("refuses a raise for an admin before spending a request on the 422", async () => {
    await mount();

    // 5000 is over the 500 this key inherits, and only a superuser may store
    // that. The admin gets the number marked, not a round trip.
    await type(field("heavy_per_day"), "5000");
    const input = field("heavy_per_day");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.body.textContent).toContain(en.quota.superuserOnly);

    await submit();
    expect(
      (fetchMock.mock.calls as [string, RequestInit][]).some(([, init]) => init?.method === "PUT")
    ).toBe(false);
  });

  it("lets a superuser store the same raise, and marks it as one", async () => {
    superuser = true;
    await mount();

    await type(field("heavy_per_day"), "5000");
    expect(field("heavy_per_day").getAttribute("aria-invalid")).toBeNull();
    expect(document.body.textContent).toContain(en.quota.superuserOnly);

    await submit();
    expect(writtenLimits().heavy_per_day).toBe(5000);
  });

  it("puts a 422 quota_above_inherited on the field it names, not in a toast", async () => {
    // No policy in the payload — a plan that moved since the read, or a worker
    // that does not report one. The client has no ceiling to check against, so
    // the server's refusal is the only one there is and it still has to land.
    respondWith([]);
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
});
