import { afterEach, describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

mock.module("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { DraftClockRing } = await import("./DraftClockRing");

const originalDateNow = Date.now;

afterEach(() => {
  Date.now = originalDateNow;
});

function renderActiveClock(now: number) {
  Date.now = () => now;

  return renderToStaticMarkup(
    <DraftClockRing
      expiresAt="2026-01-01T00:01:00.000Z"
      paused={false}
      totalSeconds={60}
      accent="live"
    />
  );
}

describe("DraftClockRing", () => {
  test("uses a deterministic placeholder for the initial server render", () => {
    const firstRender = renderActiveClock(Date.parse("2026-01-01T00:00:00.000Z"));
    const secondRender = renderActiveClock(Date.parse("2026-01-01T00:00:30.000Z"));

    expect(firstRender).toBe(secondRender);
    expect(firstRender).toContain(">--</span>");
  });
});
