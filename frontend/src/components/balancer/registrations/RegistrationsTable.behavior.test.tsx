// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditTrailProvider } from "@/components/kit/AuditTrailSheet";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import { notify } from "@/lib/notify";
import RegistrationsTable from "./RegistrationsTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listRegistrations = vi.fn();
const getRegistrationForm = vi.fn();
const listStatusCatalog = vi.fn();
const exportRegistrationsToUsers = vi.fn();
const bulkApproveRegistrations = vi.fn();
const updateRegistration = vi.fn();

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    listRegistrations: (...args: unknown[]) => listRegistrations(...args),
    getRegistrationForm: (...args: unknown[]) => getRegistrationForm(...args),
    listStatusCatalog: (...args: unknown[]) => listStatusCatalog(...args),
    exportRegistrationsToUsers: (...args: unknown[]) => exportRegistrationsToUsers(...args),
    createManualRegistration: vi.fn(),
    updateRegistration: (...args: unknown[]) => updateRegistration(...args),
    approveRegistration: vi.fn(),
    rejectRegistration: vi.fn(),
    withdrawRegistration: vi.fn(),
    restoreRegistration: vi.fn(),
    deleteRegistration: vi.fn(),
    bulkApproveRegistrations: (...args: unknown[]) => bulkApproveRegistrations(...args),
    bulkSetBalancerStatus: vi.fn(),
    setBalancerStatus: vi.fn(),
    checkInRegistration: vi.fn(),
    bulkAddToBalancer: vi.fn()
  }
}));
vi.mock("@/services/registration.service", () => ({
  default: { getForm: vi.fn().mockResolvedValue(null) }
}));

// The chips are URL-backed now, so the router mock has to actually move the
// location and re-render — a `vi.fn()` that swallows the write would make every
// filter assertion pass against a component that never saw the new value.
let currentSearch = "";
let rerender: (() => void) | null = null;
const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  currentSearch = new URL(url, "http://localhost").search;
  rerender?.();
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(currentSearch),
  usePathname: () => "/admin/tournaments/80/registration/entries",
  useRouter: () => ({ replace, push: replace })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

function statusMeta(
  value: string,
  scope: "registration" | "balancer",
  excludesFromBalancer = false,
  excludesFromReady = false
) {
  return {
    value,
    scope,
    is_builtin: true,
    kind: "builtin",
    is_override: false,
    can_edit: false,
    can_delete: false,
    can_reset: false,
    icon_slug: null,
    icon_color: null,
    name: value,
    description: null,
    excludes_from_balancer: excludesFromBalancer,
    excludes_from_ready: excludesFromReady
  };
}

function registration(id: number, overrides: Partial<AdminRegistration> = {}): AdminRegistration {
  const status = overrides.status ?? "approved";
  const balancerStatus = overrides.balancer_status ?? "ready";
  return {
    id,
    tournament_id: 80,
    workspace_id: 1,
    user_id: id,
    display_name: `Player ${id}`,
    battle_tag: `Player${id}#1234`,
    smurf_tags_json: null,
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    best_rank: null,
    roles: [],
    notes: null,
    admin_notes: null,
    custom_fields_json: null,
    status,
    status_meta: statusMeta(status, "registration"),
    balancer_status: balancerStatus,
    balancer_status_meta: statusMeta(
      balancerStatus,
      "balancer",
      balancerStatus === "not_in_balancer" || balancerStatus === "excluded"
    ),
    checked_in: false,
    profiles_open: true,
    // The server resolves admission; nothing here re-derives it. `unknown()` is
    // what the read sends for a registration outside a resolved batch, and it
    // leaves the reason tally empty — this suite is about the toolbar.
    admission: {
      decision: "not_admitted",
      requirements: [],
      blockers: [],
      overridden: [],
      checked_in: false,
      ready: false
    },
    source: "manual",
    submitted_at: "2026-07-30T17:00:00Z",
    reviewed_at: null,
    ...overrides
  } as AdminRegistration;
}

const POOL = [
  registration(1, { status: "pending", balancer_status: "not_in_balancer" }),
  ...Array.from({ length: 24 }, (_unused, index) => registration(index + 2))
];

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <RegistrationsTable tournamentId={80} />;
}

const mounted: Root[] = [];

async function mount(search = "") {
  currentSearch = search;
  window.history.replaceState(null, "", `/admin/tournaments/80/registration/entries${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <QueryClientProvider client={client}>
          {/* Each row's "Change history" action opens the shared audit drawer,
              which the admin layout mounts in the real app. */}
          <AuditTrailProvider>
            <Harness />
          </AuditTrailProvider>
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // React Query resolves through both microtasks and timers before committing.
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick();
    });
  }
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

// An open Radix menu puts `pointer-events: none` on the body; left behind, it
// swallows the next test's first click.
afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
  document.body.style.pointerEvents = "";
});

beforeEach(() => {
  // The table syncs filters, sort and paging into the URL, and jsdom keeps one
  // location per file — a leftover `?status=pending` would filter the next test.
  window.history.replaceState(null, "", "/admin/tournaments/80/registration/entries");
  currentSearch = "";
  rerender = null;
  replace.mockClear();
  listRegistrations.mockReset().mockResolvedValue(POOL);
  getRegistrationForm.mockReset().mockResolvedValue({ require_open_profile: false });
  listStatusCatalog.mockReset().mockResolvedValue([]);
  exportRegistrationsToUsers
    .mockReset()
    .mockResolvedValue({ processed: 25, skipped: 0, total: 25 });
  bulkApproveRegistrations.mockReset().mockResolvedValue({ approved: 1, skipped: 0 });
  updateRegistration.mockReset().mockResolvedValue(registration(1, { status: "pending" }));
  vi.mocked(notify.success).mockClear();
});

describe("RegistrationsTable toolbar", () => {
  it("keeps the counts in the toolbar and the footer, never in a header row", async () => {
    const scope = await mount();
    const headerText = scope.querySelector("thead")?.textContent ?? "";

    expect(headerText).not.toContain("25");
    expect(scope.textContent).toContain("1 pending");
    // Unfiltered: a single total, not a redundant "25/25".
    expect(scope.textContent).not.toContain("25/25");
    expect([...scope.querySelectorAll("span")].map((node) => node.textContent)).toContain("25");
    // Loading progress belongs to the infinite footer.
    expect(scope.textContent).toContain("Showing 25 of 25 registrations");
  });

  it("fetches the whole pool once, so the pending count survives filtering", async () => {
    await mount();

    expect(listRegistrations).toHaveBeenCalledTimes(1);
    expect(listRegistrations).toHaveBeenLastCalledWith(80, { include_deleted: false });
  });

  it("turns the pending count into the pending filter, in the URL", async () => {
    const scope = await mount();
    const chip = [...scope.querySelectorAll("button")].find((node) =>
      node.textContent?.includes("1 pending")
    );

    await click(chip);

    // Filtering no longer costs a request: the pool is already in memory.
    expect(listRegistrations).toHaveBeenCalledTimes(1);
    expect(new URLSearchParams(window.location.search).get("status")).toBe("pending");
    // 1 pending row of 25 — the other 24 are approved.
    expect(scope.querySelectorAll("tbody tr[data-row-id]").length).toBe(1);
  });

  it("lists withdrawn registrations alongside the rest", async () => {
    listRegistrations.mockResolvedValue([
      registration(1),
      registration(2, { status: "withdrawn" })
    ]);

    const scope = await mount();
    expect(scope.querySelectorAll("tbody tr[data-row-id]").length).toBe(2);
  });

  it("keeps the pending row selectable and the approved rows not", async () => {
    const scope = await mount();
    const rowCheckboxes = [...scope.querySelectorAll("tbody [role='checkbox']")];

    expect(rowCheckboxes.length).toBe(1);
  });

  it("puts every row action behind one kebab menu", async () => {
    const scope = await mount();
    const trigger = scope.querySelector("[aria-label='Actions for Player1#1234']");

    await click(trigger);

    const menu = document.body.textContent ?? "";
    expect(menu).toContain("Approve");
    expect(menu).toContain("Reject");
    expect(menu).toContain("Delete");
  });

  it("offers the shared column picker instead of its own", async () => {
    const scope = await mount();
    const trigger = [...scope.querySelectorAll("button")].find((node) =>
      node.textContent?.includes("Columns")
    );

    await click(trigger);

    expect(document.body.textContent).toContain("Reset to defaults");
  });

  it("groups the page into labelled sections on demand", async () => {
    const scope = await mount();
    const groupSelect = scope.querySelector("[aria-label='Group registrations']");

    await click(groupSelect);
    const option = [...document.querySelectorAll("[role='option']")].find((node) =>
      node.textContent?.includes("Group by check-in")
    );
    await click(option);

    // Both buckets: the pool has no checked-in rows, so one section holds all 25.
    expect(scope.textContent).toContain("25 registrations");
  });
});

describe("RegistrationsTable bulk approve", () => {
  it("undoes the batch from the toast action", async () => {
    const scope = await mount();
    await click(scope.querySelector("tbody [role='checkbox']"));
    const approveButton = [...document.querySelectorAll("button")].find((node) =>
      node.textContent?.includes("Approve 1")
    );

    await click(approveButton);

    const toast = vi
      .mocked(notify.success)
      .mock.calls.find(([message]) => message.includes("approved"));
    const action = toast?.[1]?.action as unknown as
      | { label: string; onClick: () => void }
      | undefined;
    expect(action?.label).toBe("Undo");

    await act(async () => {
      action?.onClick();
      await tick();
    });

    expect(updateRegistration).toHaveBeenCalledWith(1, { status: "pending" });
    expect(vi.mocked(notify.success).mock.calls.at(-1)?.[0]).toBe("Approval undone");
  });
});
