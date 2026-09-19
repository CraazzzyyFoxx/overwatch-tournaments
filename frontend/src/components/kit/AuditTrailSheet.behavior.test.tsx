// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AuditTrailButton,
  AuditTrailProvider,
} from "@/components/kit/AuditTrailSheet";
import { parseAuditTrailScope } from "@/components/kit/audit-log";
import { ApiError } from "@/lib/api-error";
import type { AuditLogRead } from "@/types/admin.types";
import type { PaginatedResponse } from "@/types/pagination.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listAudit = vi.fn();
const canAccessPermission = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { listAudit: (...args: unknown[]) => listAudit(...args) },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (...args: unknown[]) => canAccessPermission(...args),
  }),
}));

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <QueryClientProvider client={client}>{node}</QueryClientProvider>
      </NextIntlClientProvider>,
    );
  });
  await settle();
  // Radix renders the sheet into a portal on document.body.
  return document.body;
}

async function settle() {
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

function entry(overrides: Partial<AuditLogRead> = {}): AuditLogRead {
  return {
    id: 1,
    created_at: "2026-08-01T10:00:00Z",
    workspace_id: 3,
    actor_auth_user_id: 42,
    actor_label: "root",
    source: "admin",
    action: "tournament.update",
    entity_type: "tournament",
    entity_id: 12,
    entity_label: "Summer Cup",
    before_json: { name: "Old" },
    after_json: { name: "New" },
    reason: null,
    ip_address: null,
    user_agent: null,
    correlation_id: null,
    ...overrides,
  };
}

function page(
  results: AuditLogRead[],
  total = results.length,
): PaginatedResponse<AuditLogRead> {
  return { page: 1, per_page: 10, total, results };
}

/** The scope every test opens, matching `?history=tournament:12:3`. */
const SCOPE = { entityType: "tournament", entityId: 12, workspaceId: 3 } as const;

function trigger() {
  return [...document.body.querySelectorAll("button")].find((button) =>
    (button.getAttribute("aria-label") ?? button.textContent ?? "").includes("Change history"),
  );
}

function click(element: Element | undefined) {
  return act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("parseAuditTrailScope", () => {
  it("accepts a scope naming an entity type the writers actually use", () => {
    expect(parseAuditTrailScope("tournament:12:3")).toEqual({
      entityType: "tournament",
      entityId: 12,
      workspaceId: 3,
    });
  });

  it("rejects a prototype key posing as an entity type", () => {
    // `"toString" in ENTITY_LABELS` is true, and a drawer opened on it would
    // query an entity_type nobody writes — then report "no changes recorded".
    expect(parseAuditTrailScope("toString:1:1")).toBeNull();
    expect(parseAuditTrailScope("constructor:1:1")).toBeNull();
  });

  it("rejects malformed, partial and non-positive scopes", () => {
    expect(parseAuditTrailScope(null)).toBeNull();
    expect(parseAuditTrailScope("")).toBeNull();
    expect(parseAuditTrailScope("tournament")).toBeNull();
    expect(parseAuditTrailScope("tournament:12")).toBeNull();
    expect(parseAuditTrailScope("tournament:abc:3")).toBeNull();
    expect(parseAuditTrailScope("tournament:0:3")).toBeNull();
    expect(parseAuditTrailScope("tournament:12:-1")).toBeNull();
    expect(parseAuditTrailScope("nonsense:12:3")).toBeNull();
  });
});

describe("AuditTrailSheet", () => {
  beforeEach(() => {
    listAudit.mockReset();
    canAccessPermission.mockReset();
    canAccessPermission.mockReturnValue(true);
    document.body.innerHTML = "";
    window.history.replaceState(null, "", "/admin/tournaments/12");
  });

  it("renders no trigger without audit.read in that entity's workspace", async () => {
    // A control whose only outcome is a refusal is worse than no control.
    canAccessPermission.mockReturnValue(false);
    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} showCount />
      </AuditTrailProvider>,
    );

    expect(trigger()).toBeUndefined();
    expect(listAudit).not.toHaveBeenCalled();
  });

  it("fetches only the count until the drawer is opened", async () => {
    listAudit.mockResolvedValue(page([entry()], 1));
    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} showCount />
      </AuditTrailProvider>,
    );

    expect(listAudit).toHaveBeenCalledTimes(1);
    expect(listAudit).toHaveBeenCalledWith(
      expect.objectContaining({ per_page: 1, entity_type: "tournament", entity_id: 12 }),
    );

    await click(trigger());
    await settle();

    expect(document.body.textContent).toContain("Change history");
    expect(listAudit).toHaveBeenCalledWith(
      expect.objectContaining({ per_page: 10, workspace_id: 3 }),
    );
  });

  it("puts the open scope in the URL without adding a history entry", async () => {
    listAudit.mockResolvedValue(page([entry()], 1));
    const before = window.history.length;

    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} />
      </AuditTrailProvider>,
    );
    await click(trigger());
    await settle();

    expect(window.location.search).toContain("history=tournament%3A12%3A3");
    expect(window.history.length).toBe(before);
  });

  it("opens from a pasted link, in the workspace the link names", async () => {
    // The workspace rides in the URL because a reload leaves no component to
    // supply it, and the trail must read the journal the edit was scoped to.
    window.history.replaceState(null, "", "/admin/tournaments/12?history=tournament:12:3");
    listAudit.mockResolvedValue(page([entry()], 1));

    await mount(
      <AuditTrailProvider>
        <div />
      </AuditTrailProvider>,
    );

    expect(document.body.textContent).toContain("Change history");
    expect(listAudit).toHaveBeenCalledWith(
      expect.objectContaining({ workspace_id: 3, entity_type: "tournament", entity_id: 12 }),
    );
  });

  it("ignores a link naming an entity type nobody writes", async () => {
    window.history.replaceState(null, "", "/admin?history=toString:1:1");

    await mount(
      <AuditTrailProvider>
        <div />
      </AuditTrailProvider>,
    );

    expect(document.body.textContent).not.toContain("Change history");
    expect(listAudit).not.toHaveBeenCalled();
  });

  it("calls a refusal hidden history, never absent history", async () => {
    listAudit.mockRejectedValue(new ApiError(403, [{ msg: "Forbidden" }]));

    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} />
      </AuditTrailProvider>,
    );
    await click(trigger());
    await settle();

    expect(document.body.textContent).toContain("hidden rather than empty");
    expect(document.body.textContent).not.toContain("No changes recorded");
  });

  it("dates the journal rather than claiming the entity was never touched", async () => {
    // Empty trail + a journal that predates nothing here: the honest answer is
    // "we only know from this date", not "nobody changed it".
    listAudit.mockImplementation((params: { per_page?: number; order?: string }) =>
      Promise.resolve(
        params.order === "asc"
          ? page([entry({ created_at: "2026-07-01T00:00:00Z" })], 1)
          : page([], 0),
      ),
    );

    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} />
      </AuditTrailProvider>,
    );
    await click(trigger());
    await settle();

    expect(document.body.textContent).toContain("No changes recorded for this tournament");
    expect(document.body.textContent).toContain("Jul 1, 2026");
  });

  it("shows no count badge when nothing is recorded", async () => {
    listAudit.mockResolvedValue(page([], 0));

    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} showCount />
      </AuditTrailProvider>,
    );

    // A "0" beside the trigger asserts nothing ever happened, which is the one
    // claim the drawer's empty states exist to avoid making.
    expect(trigger()?.textContent).not.toContain("0");
  });

  it("appends the next page and reports how far the trail is read", async () => {
    const first = Array.from({ length: 10 }, (_, index) => entry({ id: index + 1 }));
    listAudit.mockImplementation((params: { page?: number; per_page?: number }) => {
      if (params.per_page === 1) return Promise.resolve(page([first[0]], 12));
      return Promise.resolve(
        params.page === 1
          ? page(first, 12)
          : page([entry({ id: 11 }), entry({ id: 12 })], 12),
      );
    });

    await mount(
      <AuditTrailProvider>
        <AuditTrailButton scope={SCOPE} />
      </AuditTrailProvider>,
    );
    await click(trigger());
    await settle();

    expect(document.body.textContent).toContain("Showing 10 of 12 changes");

    const loadMore = [...document.body.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Load more"),
    );
    await click(loadMore);
    await settle();

    expect(document.body.textContent).toContain("Showing 12 of 12 changes");
    expect(listAudit).toHaveBeenCalledWith(expect.objectContaining({ page: 2, per_page: 10 }));
  });
});
