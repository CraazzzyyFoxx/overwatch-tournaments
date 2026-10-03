import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  RESOURCE_QUERY_KEYS,
  type RealtimeResource,
  resourceQueryKeys,
} from "@/lib/realtime/resources";

type Manifest = {
  version: number;
  resources: Record<string, { scope: string }>;
};

function manifest(): Manifest {
  // The manifest lives in the backend tree and is read by path: the point is
  // that the two cannot drift, not that they share a package.
  const path = join(process.cwd(), "..", "backend", "shared", "realtime", "resources.json");
  return JSON.parse(readFileSync(path, "utf-8")) as Manifest;
}

describe("realtime resource registry", () => {
  // The parity gate. A resource published by the backend with no mapping here
  // is a query that silently never refetches — the failure mode is a stale
  // page, which is exactly what this rail exists to prevent.
  it("maps exactly the resources the manifest declares", () => {
    const declared = Object.keys(manifest().resources).sort();
    const mapped = Object.keys(RESOURCE_QUERY_KEYS).sort();

    expect(mapped).toEqual(declared);
  });

  it("keys every tournament resource off the scope id, and the form off the workspace too", () => {
    const keys = resourceQueryKeys(["tournament.registration_form"], 42, { workspaceId: 7 });

    expect(keys).toEqual([["registration-form", 7, 42]]);
  });

  // Before the workspace is known those keys cannot be built at all; emitting
  // a partial key would invalidate an unrelated query.
  it("omits workspace-bound keys until the workspace is known", () => {
    expect(resourceQueryKeys(["tournament.registration_form"], 42)).toEqual([]);
  });

  it("de-duplicates keys shared by two resources in one event", () => {
    const keys = resourceQueryKeys(["tournament.detail", "tournament.structure"], 42);
    const serialized = keys.map((key) => JSON.stringify(key));

    expect(new Set(serialized).size).toBe(serialized.length);
  });

  it("ignores a resource it does not know instead of throwing", () => {
    expect(resourceQueryKeys(["nope" as RealtimeResource], 42)).toEqual([]);
  });
});
