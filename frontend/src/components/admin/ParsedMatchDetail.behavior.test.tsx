// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ParsedMatchDetail } from "@/components/admin/ParsedMatchDetail";
import type { AdminMatchRow, LogRecordRef } from "@/types/admin.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getAdminMatch = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { getAdminMatch: (...args: unknown[]) => getAdminMatch(...args) }
}));
vi.mock("next-intl", () => ({
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
  return container;
}

function record(overrides: Partial<LogRecordRef> = {}): LogRecordRef {
  return {
    id: 77,
    filename: "Log-2026-04-20.txt",
    status: "done",
    source: "upload",
    uploader_id: 5,
    attempts: 1,
    error_message: null,
    created_at: "2026-04-20T00:00:00Z",
    started_at: "2026-04-20T00:00:01Z",
    finished_at: "2026-04-20T00:00:09Z",
    ...overrides
  };
}

function row(overrides: Partial<AdminMatchRow> = {}): AdminMatchRow {
  return {
    id: 100,
    encounter_id: 10,
    encounter_name: "A vs B",
    tournament_id: 3,
    tournament_name: "Cup",
    map_id: 8,
    map_name: "Ilios",
    home_team: { id: 1, name: "A" },
    away_team: { id: 2, name: "B" },
    home_score: 2,
    away_score: 1,
    time: 612.5,
    log_name: "Log-2026-04-20.txt",
    code: "ABC123",
    created_at: "2026-05-01T00:00:00Z",
    log_record: record(),
    ...overrides
  };
}

describe("ParsedMatchDetail", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    getAdminMatch.mockReset().mockResolvedValue({
      ...row(),
      rounds: 3,
      statistics_count: 120,
      kill_feed_count: 88,
      event_count: 40
    });
  });

  it("calls an unlinked map unresolved, never failed", async () => {
    // Most of the archive predates the ingestion table. Presenting that as a
    // failure would bury the maps whose ingestion actually broke.
    const scope = await mount(
      <ParsedMatchDetail row={row({ log_record: null })} workspaceId={1} />
    );
    expect(scope.textContent).toContain("Provenance unresolved");
    expect(scope.textContent).not.toContain("failed");
  });

  it("still shows the log name when provenance is unresolved", async () => {
    // The S3 key is built from log_name, so the log stays downloadable even
    // with no record — the admin needs to see which file it is.
    const scope = await mount(
      <ParsedMatchDetail row={row({ log_record: null })} workspaceId={1} />
    );
    expect(scope.textContent).toContain("Log-2026-04-20.txt");
  });

  it("names the record and its state when provenance resolves", async () => {
    const scope = await mount(<ParsedMatchDetail row={row()} workspaceId={1} />);
    expect(scope.textContent).toContain("#77");
    expect(scope.textContent).toContain("done");
    expect(scope.textContent).not.toContain("Provenance unresolved");
  });

  it("surfaces the ingestion error verbatim", async () => {
    // A parser error is the one field an admin cannot reconstruct elsewhere.
    const scope = await mount(
      <ParsedMatchDetail
        row={row({ log_record: record({ status: "failed", error_message: "log_not_found" }) })}
        workspaceId={1}
      />
    );
    expect(scope.textContent).toContain("log_not_found");
  });

  it("fetches the aggregates for the open row, and only with a workspace", async () => {
    // The inspector mounts this only while a row is open, so "open" is no
    // longer a prop — but the aggregates must still be scoped to a workspace,
    // never requested without one.
    await mount(<ParsedMatchDetail row={row()} workspaceId={null} />);
    expect(getAdminMatch).not.toHaveBeenCalled();

    await mount(<ParsedMatchDetail row={row()} workspaceId={1} />);
    expect(getAdminMatch).toHaveBeenCalledWith(100, 1);
  });

  it("warns when a map parsed no player statistics", async () => {
    // An accepted log that produced nothing still counts the map as played, so
    // the emptiness has to be visible rather than read as a loading state.
    getAdminMatch.mockResolvedValue({
      ...row(),
      rounds: 0,
      statistics_count: 0,
      kill_feed_count: 0,
      event_count: 0
    });
    const scope = await mount(<ParsedMatchDetail row={row()} workspaceId={1} />);
    expect(scope.textContent).toContain("No player statistics were written");
  });
});
