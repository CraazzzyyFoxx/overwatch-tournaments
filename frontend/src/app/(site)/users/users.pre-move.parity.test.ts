import { describe, expect, it } from "vitest";

import * as compareUtils from "@/app/(site)/users/compare/utils";
import * as perspective from "@/app/(site)/users/components/shared/encounter-perspective";
import * as history from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";
import { toFraction } from "@/disciplines/overwatch/character/utils";
import { native, norm, ok, PLAYERS, PRE, read, type Captures } from "@/test/users-parity";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type {
  EncounterWithUserStats,
  MatchWithUserStats,
  UserCharacterCompareResponse,
  UserCompareResponse,
  UserTournament
} from "@/types/user.types";

/**
 * §10.2 users rows, the users route's half (fixtures, renames and dropped fields: `@/test/users-parity`). The
 * captured outputs that include Overwatch figures (compare `subject_fraction`) are reproduced with the Overwatch
 * module's own functions.
 */
const UNITS = { h: "h", m: "m", s: "s" };
const COMPARE_PLAYERS = ["player", "player_away", "player_other"];
const SCOPES = ["workspace", "workspace_other", "all"];

/**
 * Legacy MVP outputs the impact_v2 cutover removed (the `performance` fact, a group's average of the old placement,
 * the badge ranked client-side): dropped from the captured side, not re-pinned.
 */
const LEGACY_MVP_OUTPUTS = new Set(["performance", "avg_mvp", "overperformance_badge"]);

/** The removed-field filter of the header, applied to the captured side only. */
const HERO_COLORS = new Set<unknown>();
const removedFields = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(removedFields);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const isHero = "slug" in record && "image_path" in record && "color" in record;
    const isMap = "gamemode_id" in record && "in_competitive" in record;
    const isMode = "slug" in record && "description" in record && !isHero;
    return Object.fromEntries(
      Object.entries(record)
        .filter(([key]) => {
          if (isHero && key === "color") HERO_COLORS.add(record[key]);
          return !(
            (isHero && key === "color") ||
            (isMap && key === "in_competitive") ||
            (isMode && key === "description") ||
            LEGACY_MVP_OUTPUTS.has(key)
          );
        })
        .map(([key, item]) => [key, removedFields(item)])
    );
  }
  return value;
};

describe("users/compare/utils.ts", () => {
  const RENAMED_QUERY: Record<string, string> = { left_entity_id: "left_hero_id", right_entity_id: "right_hero_id" };
  const text = (values: (number | null)[]) => values.map((v) => compareUtils.formatMetricValue(v ?? NaN));

  it.each(COMPARE_PLAYERS)("reproduces every captured compare derivation from the real native wire: %s", (player) => {
    const expectedUtils = read(PRE, `users-compare-utils.${player}.json`).output;
    const utils: Record<string, unknown> = {};
    for (const [label, rec] of ok(
      native<UserCompareResponse | UserCharacterCompareResponse>(`users-compare.${player}.json`),
      () => true
    )) {
      const isCharacter = label.includes(":compare_heroes:");
      const metrics = isCharacter
        ? (rec.body as UserCharacterCompareResponse).metrics.map((metric) => ({
            key: metric.stat,
            left: compareUtils.normalizeNumber(metric.left_value),
            right: compareUtils.normalizeNumber(metric.right_value),
            delta: compareUtils.normalizeNumber(metric.delta),
            delta_percent: compareUtils.normalizeNumber(metric.delta_percent),
            metric_text: text([metric.left_value, metric.right_value, metric.delta]),
            percent_text: compareUtils.formatPercent(metric.delta_percent)
          }))
        : (rec.body as UserCompareResponse).metrics.map((metric) => ({
            key: metric.key,
            subject: compareUtils.normalizeNumber(metric.subject_value),
            baseline: compareUtils.normalizeNumber(metric.baseline_value),
            delta: compareUtils.normalizeNumber(metric.delta),
            delta_percent: compareUtils.normalizeNumber(metric.delta_percent),
            percentile: compareUtils.normalizeNumber(metric.subject_percentile),
            metric_text: text([metric.subject_value, metric.baseline_value, metric.delta]),
            percent_text: compareUtils.formatPercent(metric.delta_percent),
            percentile_text: compareUtils.formatPercent(metric.subject_percentile),
            subject_fraction: toFraction(metric.subject_value)
          }));
      const characterBody = rec.body as UserCharacterCompareResponse;
      utils[label] = {
        metrics,
        map_icon: isCharacter ? compareUtils.getMapIconSrc(characterBody.map) : null,
        playtime: isCharacter
          ? {
              left: compareUtils.formatDuration(characterBody.left_playtime_seconds),
              right: compareUtils.formatDuration(characterBody.right_playtime_seconds),
              left_units: compareUtils.formatDuration(characterBody.left_playtime_seconds, UNITS)
            }
          : null,
        query_ints: Object.fromEntries(
          rec.request.query
            .filter(([key]) => key !== "discipline")
            .map(([key, value]) => [RENAMED_QUERY[key] ?? key, compareUtils.parseOptionalInt(value)])
        )
      };
    }
    expect(norm({ per_response: utils })).toEqual(expectedUtils);
  });

  it("keeps parseScope over the captured domain tokens (parseRole/roleLabelKey removed, see header)", () => {
    const expected = read(PRE, "users-compare-utils.tokens.json").output;
    const tokens = expected.domain_tokens as (string | null)[];
    expect(Object.fromEntries(tokens.map((t) => [String(t), compareUtils.parseScope(t)]))).toEqual(expected.parseScope);
  });
});

/** A native user match in the captured (old wire) form, through the header's mapping. */
const oldUserMatch = (match: MatchWithUserStats) => {
  const [one, two] = [...match.participants].sort((a, b) => a.slot - b.slot);
  const facts: Record<string, number | undefined> = match.viewer?.facts ?? {};
  const map: CatalogEntityRead = match.map;
  return {
    id: match.id,
    home_team_id: one?.tournament_team_id ?? null,
    away_team_id: two?.tournament_team_id ?? null,
    score: { home: one?.team_facts.score, away: two?.team_facts.score },
    time: match.duration_s,
    log_name: match.log_name,
    raw_status: match.raw_status,
    raw_available: match.raw_available,
    encounter_id: match.encounter_id,
    map_id: match.map_id,
    map_index: match.map_index,
    map: {
      id: map.id,
      gamemode_id: map.parent_id,
      name: map.name,
      image_path: map.image_path,
      ...(map.parent
        ? {
            gamemode: {
              id: map.parent.id,
              slug: map.parent.slug,
              name: map.parent.name,
              image_path: map.parent.image_path,
              aliases: map.parent.aliases
            }
          }
        : {}),
      aliases: map.aliases
    },
    impact_rank: facts.impact_rank ?? null,
    impact_points: facts.impact_points ?? null,
    overperformance_score: facts.overperformance_score ?? null,
    heroes: (match.viewer?.characters ?? []).map((character) => ({
      id: character.id,
      slug: character.slug,
      name: character.name,
      image_path: character.image_path,
      type: character.attrs.class,
      aliases: character.aliases
    }))
  };
};
const oldEncounter = (encounter: EncounterWithUserStats) => ({ ...encounter, matches: encounter.matches.map(oldUserMatch) });

describe("users/components/shared/encounter-perspective.ts", () => {
  it("reproduces every captured perspective and map result from the real native wire", () => {
    const fixture = read(PRE, "encounter-perspective.json");
    const selfIds: Record<string, { self_user_id: number }> = fixture.input_old_wire;
    const perResponse: Record<string, unknown> = {};
    for (const player of PLAYERS) {
      for (const [label, rec] of ok(
        native<{ results: EncounterWithUserStats[] }>(`mvp-rank.${player}.json`),
        (l) => l.endsWith(":encounters")
      )) {
        const selfId = selfIds[label].self_user_id;
        perResponse[label] = rec.body.results.map((enc) => {
          const own = perspective.encounterPerspective(enc, selfId);
          return {
            encounter_id: enc.id,
            default: own,
            explicit_team: perspective.encounterPerspective(enc, selfId, enc.user_team_id),
            unknown_team: perspective.encounterPerspective(enc, selfId, -1),
            map_kinds: enc.matches.map((m) => ({ match: m.id, kind: perspective.mapKind(m, own.own) }))
          };
        });
      }
    }
    expect(
      norm({ USER_ENCOUNTER_ENTITIES: perspective.USER_ENCOUNTER_ENTITIES, per_response: perResponse })
    ).toEqual(fixture.output);
  });
});

describe("users/components/tournaments/tournaments-history.helpers.ts", () => {
  it("reproduces every captured medal, winrate and stage record from the real native wire", () => {
    const fixture = read(PRE, "tournaments-history-helpers.json");
    const selfIds: Record<string, { self_user_id: number }> = fixture.input_old_wire;
    const perResponse: Record<string, unknown> = {};
    for (const player of PLAYERS) {
      for (const scope of SCOPES) {
        const records = native<UserTournament[] | EncounterWithUserStats[]>(`users-tournaments.${player}.${scope}.json`);
        for (const [label, rec] of ok(records as Captures<UserTournament[]>, (l) => l.endsWith(":tournaments"))) {
          const prefix = label.replace(/:tournaments$/, "");
          const selfId = selfIds[label].self_user_id;
          const tournaments = rec.body.map((t) => {
            const found = ok(records as Captures<EncounterWithUserStats[]>, (key) =>
              key.startsWith(`${prefix}:tournament_encounters:`)
            ).find(([, value]) => value.request.path.endsWith(`/tournaments/${t.id}/encounters`));
            return { ...t, encounters: found?.[1].body ?? [] };
          });
          perResponse[label] = {
            tournaments: tournaments.map((t) => {
              const pct = history.mapsWinratePct(t.maps_won, t.maps_lost);
              return {
                id: t.id,
                medal: history.placementMedal(t.placement),
                maps_winrate_pct: pct,
                winrate_color: history.winrateColor(pct),
                stages: history.groupEncountersByStage(t, selfId).map((stage) => ({
                  ...stage,
                  encounters: stage.encounters.map(oldEncounter)
                }))
              };
            })
          };
        }
      }
    }
    type Captured = { per_response: Record<string, { tournaments: Record<string, unknown>[] }>; medals: unknown };
    const captured = fixture.output as Captured;
    const withoutRoleColors = {
      per_response: Object.fromEntries(
        Object.entries(captured.per_response).map(([label, value]) => [
          label,
          {
            ...value,
            tournaments: value.tournaments.map((t) => {
              const { role_color: _role, player_role_colors: _players, ...rest } = t;
              void _role;
              void _players;
              return rest;
            })
          }
        ])
      )
    };
    expect(Object.keys(perResponse).length).toBe(18);
    expect(norm({ per_response: perResponse })).toEqual(removedFields(withoutRoleColors));
    expect(
      norm([1, 2, 3, 4, null].map((p) => [String(p), history.placementMedal(p)]))
    ).toEqual(captured.medals);
  });

  it("drops only hero colours that were the seed default", () => {
    expect([...HERO_COLORS].every((color) => color === "#ffffff")).toBe(true);
  });
});
