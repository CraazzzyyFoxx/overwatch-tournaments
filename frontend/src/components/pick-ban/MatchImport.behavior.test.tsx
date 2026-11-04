// @vitest-environment happy-dom
//
// A mix round's search by its players, from the import window: a search that gave up says why and may start again,
// but not while a filed id is still coming.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { MatchImport as MatchImportRow } from "@/types/encounter.types";

import { MatchImport, type MatchImportScope } from "./MatchImport";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listMatchImports = vi.fn();
const searchMatch = vi.fn();
vi.mock("@/services/custom-game.service", () => ({
  customGameKeys: { matchImports: (gameId: number, matchId: number) => ["imports", gameId, matchId] },
  customGameService: {
    listMatchImports: (...args: unknown[]) => listMatchImports(...args),
    searchMatch: (...args: unknown[]) => searchMatch(...args),
    importMatch: vi.fn()
  }
}));
vi.mock("@/services/pickBan.service", () => ({ default: {} }));
vi.mock("@/lib/notify", () => ({
  notify: { apiError: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));

function row(status: MatchImportRow["status"]): MatchImportRow {
  return { id: 1, status, attempts: 0, last_error: null, external_id: "7", created_at: "2026-11-01T20:00:00Z", warnings: [] };
}

async function mount(scope: Partial<Extract<MatchImportScope, { customGameId: number }>>, rows: MatchImportRow[] = []) {
  listMatchImports.mockResolvedValue(rows);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <MatchImport scope={{ customGameId: 4, encounterId: 21, onSubmitted: vi.fn(), ...scope }} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  // The round's imports resolve: the search's offer waits for them.
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
  return container;
}

const button = (container: HTMLElement, label: string) =>
  [...container.querySelectorAll("button")].find((node) => node.textContent === label);

beforeEach(() => {
  document.body.innerHTML = "";
  searchMatch.mockReset().mockResolvedValue(undefined);
});

describe("MatchImport search by players", () => {
  it("says why a search gave up and starts it again for the round", async () => {
    const onSubmitted = vi.fn();
    const scope = await mount(
      { search: "not_found", searchError: "ambiguous: 9, 10", searchable: true, onSubmitted },
      [row("failed")]
    );

    expect(scope.textContent).toContain("Several matches fit: 9, 10.");
    await act(async () => button(scope, "Search again")?.click());

    expect(searchMatch).toHaveBeenCalledWith(4, 21);
    expect(onSubmitted).toHaveBeenCalled();
  });

  it("offers a round never searched a first search", async () => {
    const scope = await mount({ search: null, searchable: true });

    expect(button(scope, "Find by players")).toBeDefined();
  });

  it("offers no search while one is looking, a filed id is coming, or the game cannot search", async () => {
    const looking = await mount({ search: "searching", searchable: true });
    const filed = await mount({ search: "not_found", searchable: true }, [row("pending")]);
    const unsearchable = await mount({ search: null, searchable: false });

    for (const scope of [looking, filed, unsearchable]) {
      expect(button(scope, "Search again") ?? button(scope, "Find by players")).toBeUndefined();
    }
  });

  it("says why a search is still waiting and when it tries again, never in the source's own words", async () => {
    const nextAttemptAt = "2026-11-01T20:05:00Z";
    const time = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(nextAttemptAt));
    const waiting = await mount({ search: "searching", searchError: "no_match_yet", searchNextAttemptAt: nextAttemptAt });
    expect(waiting.textContent).toContain("The match has not appeared in the game's records yet.");
    expect(waiting.textContent).toContain(`Next attempt at ${time}`);

    const down = await mount({ search: "searching", searchError: "source_unavailable" });
    expect(down.textContent).toContain("The match source is temporarily unavailable.");

    const raw = await mount({ search: "searching", searchError: "HTTPError 502 from upstream" });
    expect(raw.textContent).toContain("The match source returned a temporary error.");
    expect(raw.textContent).not.toContain("HTTPError");
  });

  it("links the game's uploader to a round that is searching or gave up, and to nobody else", async () => {
    const client = { instructions_url: "https://uploader.example/how", installer_url: "https://uploader.example/setup.exe" };
    const searching = await mount({ search: "searching", searchable: true, ingestClient: client });
    const gaveUp = await mount({ search: "not_found", searchable: true, ingestClient: client });
    const otherGame = await mount({ search: "searching", searchable: true });

    for (const scope of [searching, gaveUp]) {
      expect(scope.querySelector(`a[href="${client.instructions_url}"]`)).not.toBeNull();
      expect(scope.querySelector(`a[href="${client.installer_url}"]`)).not.toBeNull();
    }
    expect(otherGame.querySelector(`a[href="${client.instructions_url}"]`)).toBeNull();
  });
});
