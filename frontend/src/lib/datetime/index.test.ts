import { describe, expect, it } from "bun:test";
import { createFormatter } from "next-intl";

import { formatDateRange, resolveFormatLocale, resolveTimeZone } from ".";

describe("resolveFormatLocale", () => {
  it("keeps the viewer's own regional variant of the UI language", () => {
    expect(resolveFormatLocale("en", "en-GB,en;q=0.9")).toBe("en-GB");
    expect(resolveFormatLocale("ru", "ru-RU,ru;q=0.9,en-US;q=0.8")).toBe("ru-RU");
  });

  it("gives a 24-hour viewer their clock in the other language, never AM/PM", () => {
    // The primary tag decides, even with an en-US fallback further down the list.
    expect(resolveFormatLocale("en", "ru-RU,ru;q=0.9,en-US;q=0.8")).toBe("en-u-hc-h23");
    expect(resolveFormatLocale("ru", "en-US,en;q=0.9")).toBe("ru");
  });

  it("falls back to the UI locale without a usable header", () => {
    expect(resolveFormatLocale("en", null)).toBe("en");
    expect(resolveFormatLocale("ru", "*")).toBe("ru");
  });
});

describe("resolveTimeZone", () => {
  it("accepts any zone the runtime knows, spelled as the browser sent it", () => {
    expect(resolveTimeZone("America/New_York")).toBe("America/New_York");
  });

  it("falls back to the workspace default for a missing or bogus cookie", () => {
    expect(resolveTimeZone(undefined)).toBe("Europe/Moscow");
    expect(resolveTimeZone("Mars/Olympus_Mons")).toBe("Europe/Moscow");
  });
});

describe("formatDateRange", () => {
  it("prints tournament days as stored, whatever the viewer's zone", () => {
    const format = createFormatter({ locale: "en", timeZone: "America/New_York" });
    expect(formatDateRange(format, "2026-10-03T00:00:00Z", "2026-10-04T00:00:00Z")).toBe(
      "Oct 3 – 4, 2026"
    );
  });
});
