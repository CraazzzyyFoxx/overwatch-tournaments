import test from "node:test";
import assert from "node:assert/strict";

import {
  getInternalNavigationTarget,
  isChangedInternalNavigation,
  shouldIgnoreNavigationClick,
} from "./navigation-guard.mjs";

test("getInternalNavigationTarget returns internal relative targets", () => {
  const target = getInternalNavigationTarget("/admin/teams?page=2", "https://example.com");
  assert.equal(target, "/admin/teams?page=2");
});

test("getInternalNavigationTarget ignores external links", () => {
  const target = getInternalNavigationTarget("https://google.com/search", "https://example.com");
  assert.equal(target, null);
});

test("isChangedInternalNavigation detects changed in-app routes", () => {
  const changed = isChangedInternalNavigation(
    "https://example.com/admin/tournaments",
    "/admin/teams",
    "https://example.com"
  );
  assert.equal(changed, true);
});

test("shouldIgnoreNavigationClick ignores modifier-assisted navigation", () => {
  const ignored = shouldIgnoreNavigationClick({
    defaultPrevented: false,
    button: 0,
    metaKey: true,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
  });
  assert.equal(ignored, true);
});
