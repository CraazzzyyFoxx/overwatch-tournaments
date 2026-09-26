import { describe, expect, it } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";

import { GUIDES, type GuideId } from "./nav";

const CONTENT = join(import.meta.dirname, "_content");

describe("docs content", () => {
  // A missing file is not a build error: the article import is runtime-selected,
  // so a page registered in one language only crashes for readers of the other.
  it("every registered article has an MDX file in both locales", () => {
    const expected = (["ru", "en"] as const).flatMap((locale) =>
      (Object.keys(GUIDES) as GuideId[]).flatMap((guide) =>
        GUIDES[guide]
          .flatMap((group) => group.articles)
          .map((article) => `${locale}/${guide}/${article.slug}.mdx`),
      ),
    );
    expect(expected.filter((path) => !existsSync(join(CONTENT, path)))).toEqual([]);
  });
});
