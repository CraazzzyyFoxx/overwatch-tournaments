// @vitest-environment node
import fs from "node:fs";
import path from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AlgorithmAnalytics, PerformanceV2, TournamentAnalytics } from "@/types/analytics.types";

import * as helpers from "./analytics.helpers";
import { useAnalyticsViewModel, type AnalyticsViewModel } from "./useAnalyticsViewModel";

/**
 * §10.2 parity for the moved analytics presentation: the pre-move functions' CAPTURED outputs
 * (`__fixtures__/pre-move/analytics.*.json`, real analytics-service responses of the §10.1 parity seed through the
 * gateway, never edited) against the moved functions fed the SAME captured responses. The analytics wire did not
 * change in P7, so those responses are this code's native inputs (no post-move capture, no field pruning). Each
 * output is computed exactly as the capture spec did (`evidence/frontend-golden/analytics-run/analytics-capture.test.ts`)
 * and compared with exact `toEqual` after the capture's own JSON encoding (`undefined` → `"__undefined__"`).
 */

interface Envelope<T> {
  request: { query: [string, string | number][] | null };
  status: number;
  body: T;
}
interface Capture {
  input_old_wire: {
    analytics: Envelope<TournamentAnalytics>;
    algorithms: Envelope<{ results: AlgorithmAnalytics[] }>;
    performance: Envelope<PerformanceV2[]>;
  };
  output: Record<string, unknown>;
}

const DIRECTORY = path.resolve(__dirname, "../__fixtures__/pre-move");
const FILES = fs
  .readdirSync(DIRECTORY)
  .filter((name) => name.startsWith("analytics.") && name.endsWith(".json"))
  .sort();

/** The capture's serialization, so `undefined` members compare as the recorded marker. */
const encoded = (value: unknown): unknown =>
  JSON.parse(JSON.stringify(value, (_key, item) => (item === undefined ? "__undefined__" : item)));

function viewModel(
  analytics: TournamentAnalytics | undefined,
  perfByPlayer: Map<number, PerformanceV2> | undefined,
  canReadV2: boolean
): AnalyticsViewModel | null {
  let result: AnalyticsViewModel | null = null;
  renderToStaticMarkup(
    createElement(function Probe() {
      result = useAnalyticsViewModel(analytics, perfByPlayer, canReadV2);
      return null;
    })
  );
  return result;
}

/**
 * The owner workspace the capture passed as a UI parameter (the analytics wire carries none): the parity seed's
 * `workspace` / `workspace_other` ids (`backend/shared/testing/stats_parity.py`: `BASE = 910_000` + group offset),
 * chosen by the captured tournament key exactly as the capture spec did.
 */
const SEED_WORKSPACE_ID = { workspace: 910_000, workspace_other: 910_001 } as const;

function reproduce(capture: Capture, file: string): Record<string, unknown> {
  const analytics = capture.input_old_wire.analytics.body;
  const algorithms = capture.input_old_wire.algorithms.body.results;
  const performance = capture.input_old_wire.performance.body;
  const perfByPlayer = new Map(performance.map((row) => [row.player_id, row]));
  const query = capture.input_old_wire.analytics.request.query ?? [];
  const aid = Number(query.find(([key]) => key === "algorithm")?.[1]);
  const tid = Number(query.find(([key]) => key === "tournament_id")?.[1]);
  const workspaceId =
    file.split(".")[1] === "tournament_other" ? SEED_WORKSPACE_ID.workspace_other : SEED_WORKSPACE_ID.workspace;
  const predictedMoves = analytics.teams
    .flatMap((team) => team.players)
    .filter((player) => player.predicted_direction !== "flat").length;

  const viewModels: Record<string, AnalyticsViewModel | null> = {};
  for (const canReadV2 of [false, true]) {
    for (const hasPerformance of [false, true]) {
      viewModels[`canReadV2=${canReadV2};hasPerformance=${hasPerformance}`] = viewModel(
        analytics,
        hasPerformance ? perfByPlayer : undefined,
        canReadV2
      );
    }
  }
  viewModels.missingAnalytics = viewModel(undefined, perfByPlayer, true);

  return {
    sortAnalyticsAlgorithms: helpers.sortAnalyticsAlgorithms(algorithms),
    getPreferredAnalyticsAlgorithmId: helpers.getPreferredAnalyticsAlgorithmId(algorithms),
    canShowAnalyticsAdminToolbar: [false, true].map((allowed) => ({
      allowed,
      result: helpers.canShowAnalyticsAdminToolbar(allowed)
    })),
    getAnalyticsRefreshKeys: {
      owner: helpers.getAnalyticsRefreshKeys(workspaceId, tid, aid),
      global: helpers.getAnalyticsRefreshKeys(null, tid, aid),
      unset_workspace: helpers.getAnalyticsRefreshKeys(undefined, tid, aid),
      no_algorithm: helpers.getAnalyticsRefreshKeys(workspaceId, tid, null)
    },
    buildVerdict: helpers.buildVerdict(analytics.summary, predictedMoves),
    buildCommunityVerdict: helpers.buildCommunityVerdict(analytics.teams),
    buildKpiRail: helpers.buildKpiRail(analytics.summary, analytics.teams),
    players: analytics.teams.flatMap((team) =>
      team.players.map((player) => ({
        player_id: player.id,
        confidenceWord: helpers.confidenceWord(player.confidence),
        formatConfidencePercent: helpers.formatConfidencePercent(player.confidence),
        formatAnalyticsNumber: Object.fromEntries(
          Object.entries(player)
            .filter((entry): entry is [string, number] => typeof entry[1] === "number")
            .map(([key, value]) => [
              key,
              {
                default: helpers.formatAnalyticsNumber(value),
                integer: helpers.formatAnalyticsNumber(value, 0),
                four_digits: helpers.formatAnalyticsNumber(value, 4)
              }
            ])
        ),
        resolveImpact: {
          public: helpers.resolveImpact(perfByPlayer.get(player.id), false),
          authorized: helpers.resolveImpact(perfByPlayer.get(player.id), true),
          no_v2_row: helpers.resolveImpact(undefined, true)
        }
      }))
    ),
    teams: analytics.teams.map((team) => ({
      team_id: team.id,
      standingsRank: helpers.standingsRank(team),
      places: [team.placement, team.predicted_place].map((place) => ({
        raw: place,
        ordinal: place == null ? null : helpers.ordinal(place),
        formatPlace_en: helpers.formatPlace(place, "en"),
        formatPlace_ru: helpers.formatPlace(place, "ru")
      }))
    })),
    useAnalyticsViewModel: viewModels
  };
}

interface CapturedPlayer {
  player_id: number;
  deriveImpact?: number;
  resolveImpact: Record<"public" | "authorized" | "no_v2_row", number | null>;
}
type CapturedViewModel = { teams: Array<{ players: Array<{ id: number; impact: number | null }> }> } | null;

/**
 * Impact is no longer derived from the shift (`deriveImpact` is gone): every captured impact that came from that
 * formula is `null` now and only a readable v2 score survives. The rest of the capture is compared unchanged.
 */
function withoutDerivedImpact(capture: Capture): unknown {
  const scores = new Map(capture.input_old_wire.performance.body.map((row) => [row.player_id, row.impact_score]));
  const expected = structuredClone(capture.output) as {
    players: CapturedPlayer[];
    useAnalyticsViewModel: Record<string, CapturedViewModel>;
  };
  for (const player of expected.players) {
    delete player.deriveImpact;
    player.resolveImpact = {
      public: null,
      authorized: Number.isFinite(scores.get(player.player_id)) ? player.resolveImpact.authorized : null,
      no_v2_row: null
    };
  }
  for (const [key, model] of Object.entries(expected.useAnalyticsViewModel)) {
    const readable = key === "canReadV2=true;hasPerformance=true";
    for (const player of model?.teams.flatMap((team) => team.players) ?? []) {
      if (!readable || !Number.isFinite(scores.get(player.id))) player.impact = null;
    }
  }
  return expected;
}

describe("analytics presentation keeps its captured pre-move outputs", () => {
  it("covers both captured algorithms of every captured tournament", () => {
    expect(FILES).toHaveLength(10);
  });

  for (const name of FILES) {
    it(name, () => {
      const capture = JSON.parse(fs.readFileSync(path.join(DIRECTORY, name), "utf8")) as Capture;
      for (const envelope of Object.values(capture.input_old_wire)) expect(envelope.status).toBe(200);
      expect(capture.input_old_wire.analytics.body.teams.length).toBeGreaterThan(0);

      expect(encoded(reproduce(capture, name))).toEqual(withoutDerivedImpact(capture));
    });
  }
});
