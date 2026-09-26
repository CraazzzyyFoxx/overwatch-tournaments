import { describe, expect, it } from "vitest";

import {
  getInternalNavigationTarget,
  isChangedInternalNavigation,
  shouldIgnoreNavigationClick
} from "./navigation-guard";

const ORIGIN = "https://example.com";

describe("navigation guard", () => {
  it("returns internal relative targets", () => {
    expect(getInternalNavigationTarget("/admin/teams?page=2", ORIGIN)).toBe("/admin/teams?page=2");
  });

  it("ignores external links and non-http schemes", () => {
    expect(getInternalNavigationTarget("https://google.com/search", ORIGIN)).toBeNull();
    expect(getInternalNavigationTarget("mailto:a@example.com", ORIGIN)).toBeNull();
  });

  it("detects changed in-app routes", () => {
    expect(isChangedInternalNavigation(`${ORIGIN}/admin/tournaments`, "/admin/teams", ORIGIN)).toBe(true);
    expect(isChangedInternalNavigation(`${ORIGIN}/admin/teams`, "/admin/teams", ORIGIN)).toBe(false);
  });

  it("ignores modifier-assisted navigation", () => {
    const click = { defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
    expect(shouldIgnoreNavigationClick(click)).toBe(false);
    expect(shouldIgnoreNavigationClick({ ...click, metaKey: true })).toBe(true);
  });
});
