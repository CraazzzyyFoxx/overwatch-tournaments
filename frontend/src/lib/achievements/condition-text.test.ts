// Every node the achievement engine registers has to read as a sentence in both
// locales - a node whose message is missing renders its key path, and a node
// with no builder renders its raw params ("min time 600"), which is what this
// file exists to prevent.
import { describe, expect, it } from "vitest";
import { createTranslator } from "next-intl";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { ConditionNode } from "@/types/achievement.types";

import {
  describeCondition,
  describeLeaf,
  sentenceToLine,
  type ConditionTextOptions,
  type ConditionTranslator,
} from "./condition-text";

const HERO_NAMES: Record<string, string> = {
  "wrecking-ball": "Wrecking Ball",
  echo: "Echo",
};

function options(locale: "en" | "ru"): ConditionTextOptions {
  const t = createTranslator({
    locale,
    messages: locale === "en" ? en : (ru as typeof en),
  }) as unknown as ConditionTranslator;
  return { t, heroName: (slug) => HERO_NAMES[slug] ?? slug };
}

/** One realistic parameter set per registered engine node, including the two
 *  sub-condition-only predicates. */
const SAMPLES: Record<string, Record<string, unknown>> = {
  stat_threshold: { stat: "Eliminations", op: ">=", value: 40 },
  global_stat_sum: { stat: "HeroDamageDealt", op: ">=", value: 1000000 },
  hero_stat: { hero_slug: "wrecking-ball", stat: "KD", op: ">=", value: 5 },
  hero_kd_best: { hero_slug: "wrecking-ball", min_time: 600, min_matches: 3 },
  hero_pickrate: { op: "<", value: 0.001 },
  match_win: {},
  match_criteria: { field: "match_time", op: "<=", value: 300 },
  match_mvp_check: { stat: "ImpactRank", top_n: 3, op: "==", value: 0 },
  match_event_count: { event: "HeroSwap", op: ">=", value: 5, hero_slug: "echo" },
  fight_multikill: { min_kills: 4, op: ">=", value: 2 },
  encounter_score: { scores: [[3, 0]], round_type: "final", side: "winner" },
  encounter_revenge: {},
  encounter_result: { outcome: "win", margin: 3, opponent_score: 0, round_type: "final" },
  encounter_comeback: { min_deficit: 2 },
  bracket_path: {
    played_lower_bracket: true,
    min_lower_bracket_wins: 2,
    lost_in_round: { op: ">=", value: 3 },
  },
  tournament_format: { format: "double_elim" },
  stage_completed: { value: 2, op: "==" },
  reached_playoffs: { scope: "global", op: ">=", value: 3 },
  standing_position: { op: "<=", value: 3 },
  standing_record: { field: "wins", op: ">=", value: 5, groups_only: true },
  standing_count: { op: ">=", value: 2, position_op: "==", position_value: 1 },
  tournament_winrate: { op: ">=", value: 0.8 },
  div_level: { op: ">=", value: 5 },
  div_change: { direction: "up", min_shift: 2 },
  div_span: { op: ">=", value: 3 },
  rank_peak: { min_division: "grandmaster", role: "Tank", season: 14 },
  rank_climb: { op: ">=", value: 3, platform: "pc" },
  player_div: { op: "<=", value: 3 },
  player_role: { role: "Support" },
  is_captain: {},
  is_newcomer: { op: ">=", value: 2 },
  tournament_type: { is_league: true },
  tournament_count: { op: ">=", value: 10, is_league: null },
  draft_pick: { role: "picked", op: "<=", value: 3, autopick: false },
  registration_timing: { event: "signup", op: "<", value: -60 },
  registration_flag: { flag: "substitute", value: true },
  log_upload_count: { op: ">=", value: 5, scope: "tournament", status: "any" },
  captain_report_activity: { metric: "series_reported", op: ">=", value: 10 },
  team_players_match: {
    mode: "count",
    count_op: ">=",
    count_value: 2,
    condition: { type: "player_role", params: { role: "Tank" } },
  },
  captain_property: { condition: { type: "player_div", params: { op: "<=", value: 2 } } },
  team_otp_count: { op: ">=", value: 2 },
  teammate_recurrence: { op: ">=", value: 5 },
  global_winrate: { metric: "winrate", order: "desc", limit: 10, op: ">=", value: 0.6 },
  distinct_count: { field: "hero", op: ">=", value: 20, min_playtime: 600 },
  map_coverage: { field: "map", op: ">=", value: 10, outcome: "won" },
  map_winrate: { op: ">=", value: 0.75, min_matches: 5 },
  log_stat_rank: { stat: "HealingDealt", order: "desc", limit: 1 },
  duel_dominance: { min_kills: 10, min_diff: 5, op: ">=", value: 1 },
  consecutive: { metric: "win", min_streak: 3 },
  stable_streak: { fields: ["role", "division"], min_streak: 4 },
};

describe.each(["en", "ru"] as const)("every engine node reads as a sentence in %s", (locale) => {
  const o = options(locale);

  it.each(Object.keys(SAMPLES))("%s", (type) => {
    const line = sentenceToLine(describeLeaf(type, SAMPLES[type], o));

    expect(line.length).toBeGreaterThan(0);
    // A key path means the message is missing from the catalogue.
    expect(line).not.toContain("achievements.");
    // A raw param name ("min time 600", "hero slug") means no builder matched.
    expect(line).not.toMatch(/\b[a-z]+_[a-z]+\b/);
  });
});

describe("sentences fold the params in", () => {
  it("spells out the best-K/D node with its hero and its sample floors", () => {
    expect(sentenceToLine(describeLeaf("hero_kd_best", SAMPLES.hero_kd_best, options("en")))).toBe(
      "Best K/D on Wrecking Ball in a tournament (at least 600 s on the hero, at least 3 matches)"
    );
  });

  it("translates the same node into Russian", () => {
    expect(sentenceToLine(describeLeaf("hero_kd_best", SAMPLES.hero_kd_best, options("ru")))).toBe(
      "Лучший K/D на герое Wrecking Ball за турнир (минимум 600 с на герое, не менее 3 матчей)"
    );
  });

  it("nests a team sub-condition under the node that evaluates it", () => {
    const sentence = describeLeaf("team_players_match", SAMPLES.team_players_match, options("en"));

    expect(sentence.text).toBe("Players on the team matching the condition: at least 2");
    expect(sentence.children?.[0].text).toBe("Plays Tank");
  });

  it("reads a node the frontend has never heard of without crashing", () => {
    const line = sentenceToLine(describeLeaf("brand_new_node", { min_time: 60 }, options("en")));

    expect(line).toBe("Brand new node: Min time 60");
  });
});

describe("groups read as lists", () => {
  it("names the operator and nests its children", () => {
    const tree: ConditionNode = {
      AND: [
        { type: "match_win", params: {} },
        { NOT: { type: "is_captain", params: {} } },
      ],
    };

    const sentence = describeCondition(tree, options("en"));

    expect(sentence.group).toBe("AND");
    expect(sentence.text).toBe("All of:");
    expect(sentence.children?.map((child) => child.text)).toEqual(["Won the map", "Except:"]);
    expect(sentence.children?.[1].children?.[0].text).toBe("Captained the team");
  });
});
