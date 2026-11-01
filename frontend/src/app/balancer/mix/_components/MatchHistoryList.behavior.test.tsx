// @vitest-environment happy-dom
//
// A recorded round's log, from its history row: the parsed statistics open in the shared match dialog (without the
// `/matches/{id}` page link, a mix match lives only in its mix), a round with no statistics yet says what its log is
// doing, and a viewer allowed to file logs gets an upload that targets that round's encounter.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { MixLogUpload } from "@/app/balancer/mix/useMixLogUpload";
import type { CustomGameMatch } from "@/services/custom-game.service";

import { MatchHistoryList } from "./MatchHistoryList";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/lib/datetime/client", () => ({ useFormatter: () => ({ relativeTime: () => "just now" }) }));
vi.mock("@/components/catalog/CatalogEntityImage", () => ({ default: () => null }));
vi.mock("@/hooks/useCatalogEntities", () => ({ useCatalogEntities: () => ({ data: [] }) }));
// The dialogs are their own tests' subject: the stubs expose what the row hands them.
vi.mock("@/components/match/MatchStatsDialog", () => ({
  default: ({ matchId, showMatchLink, trigger }: { matchId: number; showMatchLink?: boolean; trigger: React.ReactNode }) => (
    <span data-testid="stats-dialog" data-match-id={matchId} data-match-link={String(showMatchLink ?? true)}>
      {trigger}
    </span>
  ),
}));
vi.mock("@/components/logs/LogUploadDialog", () => ({
  LogUploadDialog: ({ scope, trigger }: { scope: unknown; trigger: React.ReactNode }) => (
    <span data-testid="upload-dialog" data-scope={JSON.stringify(scope)}>
      {trigger}
    </span>
  ),
}));

function match(overrides: Partial<CustomGameMatch> = {}): CustomGameMatch {
  return {
    id: 21,
    teams: [
      { slot: 1, name: "Wolves", score: 1 },
      { slot: 2, name: "Bears", score: 0 },
    ],
    winner_slot: 1,
    map_id: 5,
    map_name: "King's Row",
    map_image_path: null,
    recorded_by: 9,
    recorded_at: "2026-01-01T20:00:00Z",
    points_per_win_applied: null,
    lobby_index: 0,
    bans: [],
    picks: [],
    stats_match_id: null,
    log_state: null,
    match_search: null,
    ...overrides,
  };
}

async function mount(matches: CustomGameMatch[], logUpload: MixLogUpload | null = null) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="en" messages={en}>
        <MatchHistoryList
          matches={matches}
          lobbyCount={1}
          canWrite={false}
          undoingMatchId={null}
          discipline={null}
          logUpload={logUpload}
        />
      </NextIntlClientProvider>,
    );
  });
  return container;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("MatchHistoryList log actions", () => {
  it("offers Statistics for a round with a stats match, opening it without the /matches link", async () => {
    const scope = await mount([match({ stats_match_id: 77 })]);

    const dialog = scope.querySelector('[data-testid="stats-dialog"]');
    expect(dialog?.getAttribute("data-match-id")).toBe("77");
    expect(dialog?.getAttribute("data-match-link")).toBe("false");
    expect(dialog?.querySelector('button[aria-label="Statistics"]')).not.toBeNull();
    expect(scope.textContent).not.toContain("Log processing");
  });

  it("shows a chip for the log's state while there are no statistics yet", async () => {
    const processing = await mount([match({ log_state: "processing" })]);
    expect(processing.textContent).toContain("Log processing");
    expect(processing.querySelector('[data-testid="stats-dialog"]')).toBeNull();

    const failed = await mount([match({ log_state: "failed" })]);
    expect(failed.textContent).toContain("Log failed to bind");
  });

  it("shows no chip and no statistics for a round without a log", async () => {
    const scope = await mount([match()]);

    expect(scope.textContent).not.toContain("Log processing");
    expect(scope.textContent).not.toContain("Log failed to bind");
    expect(scope.querySelector('[data-testid="stats-dialog"]')).toBeNull();
  });

  it("drops the chip once statistics exist, whatever the stale log state says", async () => {
    const scope = await mount([match({ stats_match_id: 77, log_state: "processing" })]);

    expect(scope.textContent).not.toContain("Log processing");
  });

  it("gives an uploader a per-round upload scoped to that round's encounter", async () => {
    const scope = await mount([match({ id: 21 }), match({ id: 20 })], {
      customGameId: 4,
      onUploaded: vi.fn(),
      fileUpload: true,
      matchFetch: false,
    });

    const scopes = [...scope.querySelectorAll('[data-testid="upload-dialog"]')].map((node) =>
      JSON.parse(node.getAttribute("data-scope") ?? "null"),
    );
    expect(scopes).toEqual([
      { customGameId: 4, encounterId: 21 },
      { customGameId: 4, encounterId: 20 },
    ]);
    expect(scope.querySelector('button[aria-label="Upload log"]')).not.toBeNull();
  });

  it("offers no upload to a viewer who may not file logs", async () => {
    const scope = await mount([match()]);

    expect(scope.querySelector('[data-testid="upload-dialog"]')).toBeNull();
  });

  it("offers no file upload for a game that parses no uploaded log (Deadlock)", async () => {
    const scope = await mount([match()], { customGameId: 4, onUploaded: vi.fn(), fileUpload: false, matchFetch: true });

    expect(scope.querySelector('[data-testid="upload-dialog"]')).toBeNull();
  });

  it("offers a per-round import by match ID only to a viewer who files logs for a game that fetches matches", async () => {
    const fetching = await mount([match()], { customGameId: 4, onUploaded: vi.fn(), fileUpload: false, matchFetch: true });
    expect(fetching.querySelector('button[aria-label="Import statistics by match ID"]')).not.toBeNull();

    const notFetching = await mount([match()], {
      customGameId: 4,
      onUploaded: vi.fn(),
      fileUpload: true,
      matchFetch: false
    });
    expect(notFetching.querySelector('button[aria-label="Import statistics by match ID"]')).toBeNull();

    const viewer = await mount([match()]);
    expect(viewer.querySelector('button[aria-label="Import statistics by match ID"]')).toBeNull();
  });
});
