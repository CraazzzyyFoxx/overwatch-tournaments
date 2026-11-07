import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";

import { FINAL_STATUSES, NODE_TRANSITIONS, SCHEDULE_PHASES, TOURNAMENT_PHASES } from "./lifecycle";

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
const FLOW_STATE_PY = readFileSync(join(BACKEND_CORE, "flow_state.py"), "utf8");

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

describe("tournament status parity with backend/shared/core/enums.py", () => {
  it("carries every status the enum defines, in enum order, and no invented one", () => {
    expect([...TOURNAMENT_PHASES]).toEqual(Object.values(WIRE_VALUE));
    // Every surface names a status through `common.statusBadge.<status>`.
    for (const messages of [en, ru]) {
      expect(ALL_STATUSES.filter((status) => !(status in messages.common.statusBadge))).toEqual([]);
    }
  });
});

/** Member name -> wire value of one Python `StrEnum`. */
function enumWire(className: string): Record<string, string> {
  return Object.fromEntries(
    [...section(ENUMS_PY, new RegExp(`class ${className}\\(StrEnum\\):`)).matchAll(/(\w+) = "([a-z_]+)"/g)].map(
      (entry) => [entry[1], entry[2]]
    )
  );
}

describe("node lifecycle parity with backend/shared/core/flow_state.py", () => {
  it("allows exactly the node transitions _VALID_TRANSITIONS allows", () => {
    const kinds = enumWire("FlowNodeKind");
    const statuses = enumWire("FlowNodeStatus");
    const block = section(FLOW_STATE_PY, /^_VALID_TRANSITIONS/m);
    const python: Record<string, Record<string, string[]>> = {};
    for (const kind of block.matchAll(/_K\.(\w+): \{([\s\S]*?)\n    \},/g)) {
      const moves: Record<string, string[]> = {};
      for (const move of kind[2].matchAll(/_S\.(\w+): frozenset\(\{([^}]*)\}\)/g)) {
        moves[statuses[move[1]]] = [...move[2].matchAll(/_S\.(\w+)/g)]
          .map((target) => statuses[target[1]])
          .sort();
      }
      python[kinds[kind[1]]] = moves;
    }

    const typescript = Object.fromEntries(
      Object.entries(NODE_TRANSITIONS).map(([kind, moves]) => [
        kind,
        Object.fromEntries(Object.entries(moves).map(([from, to]) => [from, [...to].sort()]))
      ])
    );

    expect(typescript).toEqual(python);
  });

  it("schedules exactly the phases SCHEDULE_PHASES allows", () => {
    const kinds = enumWire("FlowNodeKind");
    const block = section(FLOW_STATE_PY, /^SCHEDULE_PHASES/m);
    const python = Object.fromEntries(
      [...block.matchAll(/_K\.(\w+): frozenset\(\{([^}]*)\}\)/g)].map((entry) => [
        kinds[entry[1]],
        [...entry[2].matchAll(/"(\w+)"/g)].map((phase) => phase[1]).sort()
      ])
    );
    const typescript = Object.fromEntries(
      Object.entries(SCHEDULE_PHASES).map(([kind, phases]) => [kind, [...phases].sort()])
    );

    expect(typescript).toEqual(python);
  });

  it("treats exactly FINAL_STATUSES as a final output", () => {
    const statuses = enumWire("FlowNodeStatus");
    const block = section(FLOW_STATE_PY, /^FINAL_STATUSES/m);
    const python = [...block.matchAll(/FlowNodeStatus\.(\w+)/g)].map((entry) => statuses[entry[1]]).sort();

    expect([...FINAL_STATUSES].sort()).toEqual(python);
  });
});
