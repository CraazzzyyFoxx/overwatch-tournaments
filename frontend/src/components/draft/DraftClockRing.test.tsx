import { afterEach, describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { formatClock } from "@/hooks/usePickCountdown";
import type { DraftPick } from "@/types/draft.types";

// Module mocks are process-wide in bun: every mock of next-intl in the draft
// suite exposes the same hooks, or whichever file loads first breaks the rest.
mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));
mock.module("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "", number: (value: number) => String(value), relativeTime: () => "" })
}));

// Dynamic: `mock.module` only applies to modules imported after it runs.
const { DraftClockRing } = await import("./DraftClockRing");

const originalDateNow = Date.now;

afterEach(() => {
  Date.now = originalDateNow;
});

const pick = (overrides: Partial<DraftPick> = {}): DraftPick => ({
  id: 1,
  session_id: 1,
  overall_no: 1,
  round_no: 1,
  pick_in_round: 1,
  draft_team_id: 10,
  target_role: null,
  target_rank_value: null,
  status: "on_clock",
  picked_player_id: null,
  picked_by_user_id: null,
  is_autopick: false,
  is_admin_override: false,
  clock_started_at: null,
  clock_expires_at: "2026-01-01T00:01:00.000Z",
  overtime_started_at: null,
  version: 1,
  ...overrides
});

function renderActiveClock(now: number, size?: "md" | "sm") {
  Date.now = () => now;

  return renderToStaticMarkup(
    <DraftClockRing pick={pick()} paused={false} totalSeconds={60} size={size} />
  );
}

describe("DraftClockRing", () => {
  test("uses a deterministic placeholder for the initial server render", () => {
    const firstRender = renderActiveClock(Date.parse("2026-01-01T00:00:00.000Z"));
    const secondRender = renderActiveClock(Date.parse("2026-01-01T00:00:30.000Z"));

    expect(firstRender).toBe(secondRender);
    expect(firstRender).toContain(">--</span>");
    expect(firstRender).toContain('role="timer"');
  });

  test("the strip ring is the 52px variant", () => {
    const html = renderActiveClock(Date.parse("2026-01-01T00:00:00.000Z"), "sm");

    expect(html).toContain('width="52"');
    expect(html).not.toContain('width="88"');
  });

  test("overtime is named, not only coloured", () => {
    // The main clock is spent; `clock_expires_at` now carries the overtime
    // deadline, so the label has to say which clock the number belongs to.
    const html = renderToStaticMarkup(
      <DraftClockRing
        pick={pick({ overtime_started_at: "2026-01-01T00:00:45.000Z" })}
        paused={false}
        totalSeconds={60}
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

  test("clock text is m:ss, and +m:ss in overtime", () => {
    expect(formatClock(75_000, false)).toBe("1:15");
    expect(formatClock(9_200, false)).toBe("0:10");
    expect(formatClock(12_000, true)).toBe("+0:12");
  });
});
