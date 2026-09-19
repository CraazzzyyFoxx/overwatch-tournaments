import { describe, it, expect } from "bun:test";
import { createTranslator } from "next-intl";

import en from "./messages/en.json";
import ru from "./messages/ru.json";

/**
 * The veto/encounter namespaces lean on ICU plurals, and Russian needs four
 * categories where English needs two. A malformed plural does not throw at
 * build time — next-intl reports it through `onError` and renders the dotted
 * key instead, so a broken message ships as visible gibberish. These tests
 * render every message in both locales with arguments derived from its own
 * placeholders and fail on any reported error or unresolved key.
 *
 * `encounters.veto.room` is the veto room's own namespace and carries slot-mode
 * plurals of its own. `encounters.detail` joined it once the encounter detail
 * page grew map/report counters — same four-category Russian risk, same silent
 * failure mode. (The former `mapVeto` / `mapVetoAdmin` namespaces were deleted:
 * the veto UI addresses `encounters.veto.*` and `pickBan.*`, and nothing had
 * read those two since.)
 */
const NAMESPACES = ["encounters.veto.room", "encounters.detail"] as const;

type Leaf = { key: string; message: string };

function leaves(value: unknown, prefix: string): Leaf[] {
  if (typeof value === "string") return [{ key: prefix, message: value }];
  if (value === null || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) =>
    leaves(v, `${prefix}.${k}`)
  );
}

/**
 * Top-level ICU argument names. Matches `{name}` and the `{name, plural, …}` /
 * `{name, select, …}` forms, skipping the `#` inside a plural body because it
 * carries no argument name of its own.
 */
function argNames(message: string): string[] {
  return [...message.matchAll(/\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*[,}]/g)].map((match) => match[1]);
}

/** The argument a plural selects on — `count` in `{count, plural, …}`. */
function pluralArg(message: string): string | null {
  return message.match(/\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*,\s*plural\s*,/)?.[1] ?? null;
}

/**
 * XML-ish tag names a message expects the call site to supply a renderer for
 * (`<em>…</em>` in a hero title). Rendering through `t()` without them is a
 * FORMATTING_ERROR, so the checks below pass a stub per tag.
 */
function tagNames(message: string): string[] {
  return [...new Set([...message.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)>/g)].map((m) => m[1]))];
}

function argsFor(message: string): Record<string, unknown> {
  // A number satisfies both `{count, plural, …}` and a bare `{stage}`.
  return {
    ...Object.fromEntries(argNames(message).map((name) => [name, 1])),
    ...Object.fromEntries(tagNames(message).map((tag) => [tag, (chunks: string) => chunks]))
  };
}

function collectLeaves(messages: typeof en): Leaf[] {
  return NAMESPACES.flatMap((namespace) =>
    leaves(
      // Dotted walk: `encounters.veto.room` is not a top-level key.
      namespace
        .split(".")
        .reduce<unknown>(
          (node, key) => (node as Record<string, unknown> | undefined)?.[key],
          messages as Record<string, unknown>
        ),
      namespace
    )
  );
}

describe.each([
  ["en", en],
  ["ru", ru]
])("map-veto messages render in %s", (locale, messages) => {
  const entries = collectLeaves(messages as typeof en);

  it("has messages to check", () => {
    expect(entries.length).toBeGreaterThan(100);
  });

  it("resolves every key with no ICU error and no leftover placeholder", () => {
    const errors: string[] = [];
    const t = createTranslator({
      locale,
      messages: messages as typeof en,
      onError: (error) => errors.push(String(error))
    });

    const unresolved: string[] = [];
    const leftover: string[] = [];

    for (const { key, message } of entries) {
      const rendered = t(key as never, argsFor(message) as never);

      if (rendered === key) unresolved.push(key);
      if (typeof rendered === "string" && /[{}]/.test(rendered)) leftover.push(key);
    }

    expect({ errors, unresolved, leftover }).toEqual({
      errors: [],
      unresolved: [],
      leftover: []
    });
  });

  it("selects a plural category for every count, including Russian few/many", () => {
    const errors: string[] = [];
    const t = createTranslator({
      locale,
      messages: messages as typeof en,
      onError: (error) => errors.push(String(error))
    });
    const plurals = entries.filter(({ message }) => pluralArg(message) !== null);

    expect(plurals.length).toBeGreaterThan(0);

    // 1 / 2 / 5 / 21 hit Russian one / few / many / one respectively, so a
    // catalogue missing `few` or `many` renders the `other` branch and is caught.
    const counts = [1, 2, 5, 21];
    const rendered: Record<string, string[]> = {};

    for (const { key, message } of plurals) {
      const arg = pluralArg(message);
      if (arg === null) continue;
      // Sibling arguments and tag renderers must still be present or ICU
      // refuses to format.
      const base = argsFor(message);
      rendered[key] = counts.map(
        (count) => t(key as never, { ...base, [arg]: count } as never) as string
      );
    }

    const notInterpolated = Object.entries(rendered).flatMap(([key, texts]) =>
      texts.flatMap((text, index) =>
        typeof text === "string" && text.includes(String(counts[index]))
          ? []
          : [`${key} @ ${counts[index]}`]
      )
    );

    expect({ errors, notInterpolated }).toEqual({ errors: [], notInterpolated: [] });
  });
});

describe("Russian plural completeness", () => {
  // GLOSSARY.md: "Числа: русская плюрализация через ICU (plural с one/few/many/other)".
  // ICU legally falls back to `other`, so a catalogue declaring only one/other
  // renders grammatically wrong Russian without any error — nothing but an
  // explicit category check catches it.
  it("declares one/few/many/other for every plural in the map-veto namespaces", () => {
    const incomplete = collectLeaves(ru as typeof en)
      .filter(({ message }) => pluralArg(message) !== null)
      .flatMap(({ key, message }) => {
        const missing = (["one", "few", "many", "other"] as const).filter(
          (category) => !new RegExp(`\\b${category}\\s*\\{`).test(message)
        );
        return missing.length > 0 ? [{ key, missing }] : [];
      });

    expect(incomplete).toEqual([]);
  });
});
