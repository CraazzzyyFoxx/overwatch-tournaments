import { describe, it, expect } from "bun:test";

import en from "./messages/en.json";
import ru from "./messages/ru.json";

function keyPaths(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    keyPaths(v, prefix ? `${prefix}.${k}` : k),
  );
}

describe("message dictionaries", () => {
  it("en and ru have identical key sets", () => {
    const enKeys = new Set(keyPaths(en));
    const ruKeys = new Set(keyPaths(ru));
    const missingInRu = [...enKeys].filter((k) => !ruKeys.has(k));
    const missingInEn = [...ruKeys].filter((k) => !enKeys.has(k));
    expect({ missingInRu, missingInEn }).toEqual({ missingInRu: [], missingInEn: [] });
  });
});

/**
 * Keys looked up by INTERPOLATION rather than as literals, which the parity check
 * above cannot see: both dictionaries can agree perfectly and still be missing
 * one. The overview's Format card renders team formation as
 * `t(`common.${tournament.team_formation}`)`, and adding the `registration` mode
 * shipped a badge reading the raw path `common.registration` because no key
 * existed and the TS cast claimed the value could not occur.
 */
describe("interpolated message keys", () => {
  it("every team_formation value has a common.* label in both locales", () => {
    // The full set the backend column can hold; `Tournament.team_formation` is a
    // free string, so this list is the contract.
    const formations = ["balancer", "draft", "registration", "solo"];
    for (const dict of [en, ru]) {
      const common: Record<string, unknown> = dict.common;
      expect(formations.filter((value) => !(value in common))).toEqual([]);
    }
  });

  // A "two team tabs must not share a label" assertion lived here. It is gone
  // with the tab itself: registered teams render on the Participants page, so
  // `common.teams` is the only team-labelled section and `registrationTeams.tab`
  // no longer exists. `tournament-section-nav.test.ts` now pins that there is
  // exactly one such section, which is the stronger claim.
});
