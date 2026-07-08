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
