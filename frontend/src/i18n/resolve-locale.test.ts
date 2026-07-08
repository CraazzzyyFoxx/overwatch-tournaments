import { describe, it, expect } from "bun:test";

import { resolveLocale } from "./resolve-locale";

describe("resolveLocale", () => {
  it("prefers a valid cookie value", () => {
    expect(resolveLocale("en", "ru,en;q=0.9")).toBe("en");
    expect(resolveLocale("ru", null)).toBe("ru");
  });

  it("ignores an invalid cookie and falls back to Accept-Language", () => {
    expect(resolveLocale("de", "ru-RU,ru;q=0.9")).toBe("ru");
    expect(resolveLocale("", "en-US,en;q=0.9")).toBe("en");
  });

  it("uses Accept-Language when no cookie: ru wins only if ru is present", () => {
    expect(resolveLocale(undefined, "ru-RU,ru;q=0.9,en;q=0.8")).toBe("ru");
    expect(resolveLocale(undefined, "fr-FR,fr;q=0.9")).toBe("en");
  });

  it("defaults to ru when nothing is available", () => {
    expect(resolveLocale(undefined, null)).toBe("ru");
  });
});
