import { describe, expect, it } from "bun:test";

import { getUtcOffsetLabel, utcToZonedInput, zonedInputToUtc } from "./timezone";

describe("utcToZonedInput", () => {
  it("renders a UTC instant as MSK wall clock", () => {
    expect(utcToZonedInput("2026-01-15T15:00:00Z", "Europe/Moscow")).toBe("2026-01-15T18:00");
  });

  it("crosses the date line when the zone is ahead of UTC", () => {
    expect(utcToZonedInput("2026-01-15T22:30:00Z", "Europe/Moscow")).toBe("2026-01-16T01:30");
  });

  it("returns empty string for blank and invalid values", () => {
    expect(utcToZonedInput(null, "Europe/Moscow")).toBe("");
    expect(utcToZonedInput("", "Europe/Moscow")).toBe("");
    expect(utcToZonedInput("not-a-date", "Europe/Moscow")).toBe("");
  });
});

describe("zonedInputToUtc", () => {
  it("parses MSK wall clock into a UTC instant", () => {
    expect(zonedInputToUtc("2026-01-15T18:00", "Europe/Moscow")).toBe("2026-01-15T15:00:00.000Z");
  });

  it("handles DST zones on both sides of the switch", () => {
    // New York: EST (UTC-5) in January, EDT (UTC-4) in July.
    expect(zonedInputToUtc("2026-01-10T12:00", "America/New_York")).toBe(
      "2026-01-10T17:00:00.000Z"
    );
    expect(zonedInputToUtc("2026-07-10T12:00", "America/New_York")).toBe(
      "2026-07-10T16:00:00.000Z"
    );
  });

  it("returns null for blank or malformed input", () => {
    expect(zonedInputToUtc("", "Europe/Moscow")).toBeNull();
    expect(zonedInputToUtc("15:00", "Europe/Moscow")).toBeNull();
  });

  it("round-trips through utcToZonedInput", () => {
    const iso = zonedInputToUtc("2026-03-08T02:30", "Europe/Moscow");
    expect(iso).not.toBeNull();
    expect(utcToZonedInput(iso, "Europe/Moscow")).toBe("2026-03-08T02:30");
  });
});

describe("getUtcOffsetLabel", () => {
  it("labels fixed-offset zones", () => {
    expect(getUtcOffsetLabel("Europe/Moscow", new Date("2026-01-15T00:00:00Z"))).toBe("UTC+3");
  });

  it("labels half-hour offsets", () => {
    expect(getUtcOffsetLabel("Asia/Kolkata", new Date("2026-01-15T00:00:00Z"))).toBe("UTC+5:30");
  });

  it("labels negative offsets", () => {
    expect(getUtcOffsetLabel("America/New_York", new Date("2026-01-15T00:00:00Z"))).toBe("UTC-5");
  });
});
