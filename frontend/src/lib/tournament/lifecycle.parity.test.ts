import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  SCHEDULABLE_PHASES,
  TOURNAMENT_PHASES,
  TOURNAMENT_STATUS_LABELS,
  VALID_TRANSITIONS
} from "./lifecycle";

/**
 * The lifecycle machine exists twice — once in Python, once in TypeScript —
 * because the browser cannot import the server's enum and a round trip to ask
 * "what may this status become" would be absurd for a constant.
 *
 * A hand-mirrored constant with no drift check is a rumour: the frontend copy
 * would keep offering a transition the server rejects, or hide one it allows,
 * and every unit test on both sides would still be green. So this reads the
 * Python source and compares. It is intentionally a source-text scan and not a
 * generated artifact — a generator would need a build step in the loop of every
 * backend edit, while this fails in the same suite the change already runs.
 */
const BACKEND_CORE = join(import.meta.dirname, "..", "..", "..", "..", "backend", "shared", "core");
const ENUMS_PY = readFileSync(join(BACKEND_CORE, "enums.py"), "utf8");
const MACHINE_PY = readFileSync(join(BACKEND_CORE, "tournament_state.py"), "utf8");

/**
 * One top-level Python construct: its opening line plus everything indented
 * under it, closing bracket included. Ends at the next line that starts in
 * column 0 with something other than a closer — which is exactly where the
 * next statement, comment or class begins.
 */
function section(source: string, start: RegExp): string {
  const match = start.exec(source);
  if (!match) throw new Error(`no ${start} in the Python source`);
  const [head, ...rest] = source.slice(match.index).split("\n");
  const body = [head];
  for (const line of rest) {
    if (line.length > 0 && !/^[\s)}\]]/.test(line)) break;
    body.push(line);
  }
  return body.join("\n");
}

/** Member name (`CHECK_IN`) -> wire value (`"check_in"`), from the enum itself. */
const WIRE_VALUE: Record<string, string> = Object.fromEntries(
  [...section(ENUMS_PY, /class TournamentStatus\(StrEnum\):/).matchAll(/(\w+) = "([a-z_]+)"/g)].map(
    (entry) => [entry[1], entry[2]]
  )
);

const ALL_STATUSES = Object.values(WIRE_VALUE).sort();

function wire(member: string): string {
  const value = WIRE_VALUE[member];
  if (value === undefined) throw new Error(`TournamentStatus.${member} is not in the enum`);
  return value;
}

function members(block: string): string[] {
  return [...block.matchAll(/TournamentStatus\.(\w+)/g)].map((entry) => wire(entry[1]));
}

describe("tournament lifecycle parity with backend/shared/core", () => {
  it("carries every status the enum defines, and no invented one", () => {
    expect([...TOURNAMENT_PHASES].sort()).toEqual(ALL_STATUSES);
    expect(Object.keys(TOURNAMENT_STATUS_LABELS).sort()).toEqual(ALL_STATUSES);
  });

  it("orders the phases exactly as PHASE_ORDER does", () => {
    const ordered = [
      ...section(MACHINE_PY, /^PHASE_ORDER: dict/m).matchAll(/TournamentStatus\.(\w+): (\d+)/g)
    ]
      .sort((a, b) => Number(a[2]) - Number(b[2]))
      .map((entry) => wire(entry[1]));

    expect([...TOURNAMENT_PHASES]).toEqual(ordered);
  });

  it("schedules exactly the phases SCHEDULABLE_STATUSES allows", () => {
    const python = members(section(MACHINE_PY, /^SCHEDULABLE_STATUSES/m));

    expect([...SCHEDULABLE_PHASES].sort()).toEqual(python.sort());
  });

  it("allows exactly the transitions _VALID_TRANSITIONS allows", () => {
    const block = section(MACHINE_PY, /^_VALID_TRANSITIONS/m);
    const python: Record<string, string[]> = {};
    for (const entry of block.matchAll(/TournamentStatus\.(\w+): frozenset\(\s*\{([^}]*)\}/g)) {
      python[wire(entry[1])] = members(entry[2]).sort();
    }

    const typescript = Object.fromEntries(
      Object.entries(VALID_TRANSITIONS).map(([from, to]) => [from, [...to].sort()])
    );

    expect(typescript).toEqual(python);
  });
});
