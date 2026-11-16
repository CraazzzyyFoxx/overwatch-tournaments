// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditTrailProvider } from "@/components/kit/AuditTrailSheet";
import { en as kitMessages } from "@craazzzyyfoxx/admin-kit/messages";
import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import RegistrationsTable from "./RegistrationsTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const careerSignals = vi.fn();
const permissions = vi.hoisted(() => ({ rankRead: true }));

const MESSAGES = {
  common: en.common,
  kit: en.kit,
  kitAudit: en.kitAudit,
  kitTable: en.kitTable,
  ...kitMessages,
  registrationsAdmin: en.registrationsAdmin,
  registrationOrganizer: en.registrationOrganizer,
  rosterShape: en.rosterShape,
  registrationNotes: en.registrationNotes,
  admission: en.admission
};

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    listRegistrations: async () => POOL,
    getRegistrationForm: async () => ({ require_open_profile: false }),
    listStatusCatalog: async () => []
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: async () => ({ id: 80, workspace_id: 1, discipline: "overwatch" }),
    getCareerSignals: (...args: unknown[]) => careerSignals(...args)
  }
}));
vi.mock("@/services/registration-note.service", () => ({
  default: { counts: async () => ({ registrations: {} }), list: async () => [] }
}));
vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);
vi.mock("@/services/registration.service", () => ({ default: { getForm: vi.fn().mockResolvedValue(null) } }));

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
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => permission !== "rank.read" || permissions.rankRead
  })
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() } }));

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
    entry_id: id + 1000,
    registration_node_id: 7,
    tournament_id: 80,
    workspace_id: 1,
    user_id: id,
    display_name: `Player ${id}`,
    primary_handle: `Player${id}#1234`,
    best_rank: null,
    roles: [],
    answers: { identity_battlenet: [`Player${id}#1234`], stream_pov: false },
    form_version_id: 3,
    form_version_stale: false,
    admin_notes: null,
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
  registration(1),
  registration(2),
  registration(3),
  registration(4, { user_id: null })
];

const signalsOf = (
  userId: number,
  signals: { code: string; social_account_id?: number | null; handle?: string | null; value?: number | null }[],
  userName: string | null = `Player${userId}#1234`
) => ({
  user_id: userId,
  user_name: userName,
  competitive_role_shares: { support: 0.6, damage: 0.4 },
  hours: 123.4,
  last_played_at: "2026-10-01T00:00:00Z",
  signals: signals.map((signal) => ({ social_account_id: null, handle: null, value: null, ...signal }))
});

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
  return <RegistrationsTable tournamentId={80} registrationNodeId={7} />;
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
      <NextIntlClientProvider locale="en" messages={MESSAGES}>
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

afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
});

beforeEach(() => {
  currentSearch = "";
  rerender = null;
  permissions.rankRead = true;
  careerSignals.mockReset().mockResolvedValue({
    generated_at: "",
    users: [
      signalsOf(1, []),
      signalsOf(2, [{ code: "profile_not_found", social_account_id: 11 }]),
      signalsOf(3, [
        { code: "low_hours_high_rank", social_account_id: 11, handle: "main#1111", value: 42 },
        { code: "renamed", social_account_id: 12, handle: "smurf#2222" }
      ])
    ]
  });
});

/** The ladder cell of each row, in row order. */
const ladderCells = (scope: HTMLElement) => {
  const headers = [...scope.querySelectorAll("thead th")];
  const index = headers.findIndex((header) => header.textContent?.trim() === "Ladder");
  return index < 0
    ? null
    : [...scope.querySelectorAll("tbody tr[data-row-id]")].map((row) => row.querySelectorAll("td")[index]);
};

describe("registrations career signals", () => {
  it("shows a tick, the one signal's chip, a count for several, and a dash without a linked user", async () => {
    const scope = await mount();
    const cells = ladderCells(scope);
    expect(cells).not.toBeNull();
    const byRow = Object.fromEntries(cells!.map((cell) => [cell.closest("tr")?.getAttribute("data-row-id"), cell]));
    expect(byRow["1"].querySelector("svg[aria-label='No signals']")).not.toBeNull();
    expect(byRow["2"].textContent).toBe("Tag not found");
    expect(byRow["3"].textContent).toBe("2 signals");
    expect(byRow["4"].textContent).toBe("—");
    // One batched read for the whole page, the linked users only.
    expect(careerSignals).toHaveBeenCalledTimes(1);
    expect(careerSignals).toHaveBeenCalledWith("overwatch", 1, [1, 2, 3]);
  });

  it("hides the column quietly when the read is forbidden", async () => {
    careerSignals.mockRejectedValue(new ApiError(403, [{ msg: "forbidden" }]));
    const scope = await mount();
    expect(ladderCells(scope)).toBeNull();
    expect(scope.textContent).not.toContain("Ladder");
  });

  it("does not ask without rank.read", async () => {
    permissions.rankRead = false;
    const scope = await mount();
    expect(ladderCells(scope)).toBeNull();
    expect(careerSignals).not.toHaveBeenCalled();
  });

  it("lists the inspector's signals with the account they name, hours and the role split", async () => {
    const scope = await mount("?id=3");
    const text = document.body.textContent ?? "";
    expect(text).toContain("Only 42 h at a high rank · main#1111");
    expect(text).toContain("The game shows another name · smurf#2222");
    expect(text).toContain("123 h in total");
    expect(text).toContain("Support60%");
    expect(document.querySelector("a[href='/users/Player3-1234?tab=ladder']")).not.toBeNull();
    expect(scope).toBeTruthy();
  });

  it("draws no profile link when the server names no player", async () => {
    careerSignals.mockResolvedValue({ generated_at: "", users: [signalsOf(3, [], null)] });
    await mount("?id=3");
    expect(document.body.textContent).toContain("123 h in total");
    expect(document.querySelector("a[href*='tab=ladder']")).toBeNull();
  });
});
