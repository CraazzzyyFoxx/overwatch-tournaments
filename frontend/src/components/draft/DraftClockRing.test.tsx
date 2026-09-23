import { afterEach, describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key,
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

  test("overtime is named, not only coloured", () => {
    // The main clock is spent; `expiresAt` now carries the overtime deadline,
    // so the label has to say which clock the number belongs to.
    const html = renderToStaticMarkup(
      <DraftClockRing
        expiresAt="2026-01-01T00:01:00.000Z"
        paused={false}
        totalSeconds={60}
        accent="urgent"
        overtimeStartedAt="2026-01-01T00:00:45.000Z"
        overtimeSeconds={15}
      />
    );

    expect(html).toContain("draft.clock.overtime");
    expect(html).toContain("var(--aqt-live)");
  });

  test("the main clock never claims overtime", () => {
    const html = renderActiveClock(Date.parse("2026-01-01T00:00:00.000Z"));

    expect(html).not.toContain("draft.clock.overtime");
  });
});
