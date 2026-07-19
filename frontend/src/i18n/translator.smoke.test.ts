import { describe, it, expect } from "bun:test";
import { createTranslator } from "next-intl";

import en from "./messages/en.json";
import ru from "./messages/ru.json";

// Pure (non-React) smoke of the message pipeline: key resolution and ICU
// interpolation per locale, matching the repo's logic-only test style.
describe("next-intl translator over the JSON bundles", () => {
  it("resolves the same key to each locale's text", () => {
    const tRu = createTranslator({ locale: "ru", messages: ru });
    const tEn = createTranslator({ locale: "en", messages: en });

    expect(tRu("common.back")).toBe(ru.common.back);
    expect(tEn("common.back")).toBe(en.common.back);
    expect(tRu("common.back")).not.toBe(tEn("common.back"));
  });

  it("interpolates {var} placeholders", () => {
    const tEn = createTranslator({ locale: "en", messages: en });
    expect(tEn("common.teamsCount", { count: 3 })).toContain("3");
  });

  it("resolves dynamically-built nested keys (shim call-site pattern)", () => {
    const tEn = createTranslator({ locale: "en", messages: en });
    const status = "live";
    expect(tEn(`common.statusBadge.${status}` as "common.statusBadge.live")).toBe(
      en.common.statusBadge.live,
    );
  });
});
