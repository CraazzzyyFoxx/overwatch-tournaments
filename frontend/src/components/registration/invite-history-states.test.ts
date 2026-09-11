import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "bun:test";

/**
 * The invite ledger renders on two screens — the captain's panel and the
 * organizer's teams browser — and each keeps its own list of the states the
 * server can send. That duplication is deliberate: the two sections are otherwise
 * uncoupled, and importing one into the other would make either fail to build
 * without the other.
 *
 * What is NOT acceptable is the lists drifting. A state present in one and
 * missing from the other renders as a translated label on one screen and as a
 * raw wire code on the other, for the same row — and the mismatch is invisible
 * to both mount tests, because each only ever sees its own list.
 */
const ROOT = join(import.meta.dir, "..", "..");

const SITES = {
  captain: join(ROOT, "components", "registration", "InviteHistorySection.tsx"),
  organizer: join(
    ROOT,
    "app",
    "admin",
    "tournaments",
    "[id]",
    "components",
    "RegistrationTeamsBrowser.tsx"
  )
} as const;

function historyStates(path: string): string[] {
  const source = readFileSync(path, "utf8");
  const match = /const HISTORY_STATES = \[([^\]]+)\] as const;/.exec(source);
  if (!match) throw new Error(`no HISTORY_STATES in ${path}`);
  return [...match[1].matchAll(/"([a-z_]+)"/g)].map((entry) => entry[1]);
}

describe("invite history states", () => {
  it("are the same on both screens", () => {
    const captain = historyStates(SITES.captain);
    const organizer = historyStates(SITES.organizer);

    // Sorted arrays rather than sets: on failure the diff names the state that
    // drifted, which a set-equality failure does not.
    expect([...captain].sort()).toEqual([...organizer].sort());
  });

  it("cover exactly the vocabulary the server can send", () => {
    // `expired` is the one that is NOT a stored column value — the server derives
    // it from a pending row past its clock — so a list built by reading the
    // database enum would silently miss it.
    expect([...historyStates(SITES.captain)].sort()).toEqual([
      "accepted",
      "declined",
      "expired",
      "pending",
      "revoked"
    ]);
  });

  it("each have a translation in both locales", () => {
    // The mount tests prove the component asks for these keys; this proves the
    // dictionaries answer, for every state, in both languages.
    const en = JSON.parse(readFileSync(join(ROOT, "i18n", "messages", "en.json"), "utf8"));
    const ru = JSON.parse(readFileSync(join(ROOT, "i18n", "messages", "ru.json"), "utf8"));

    for (const state of historyStates(SITES.captain)) {
      expect(en.registrationTeams.history.state[state]).toBeString();
      expect(ru.registrationTeams.history.state[state]).toBeString();
      // A Russian value identical to the English one is almost always a
      // copy-paste that never got translated.
      expect(ru.registrationTeams.history.state[state]).not.toBe(
        en.registrationTeams.history.state[state]
      );
    }
  });
});
