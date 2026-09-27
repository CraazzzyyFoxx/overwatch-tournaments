import { describe, expect, it } from "vitest";

import { BadgeHelp, ShieldOff } from "lucide-react";

import { STATUS_ICON_OPTIONS, getStatusIcon } from "./status-icons";

// Resolution used to go through a `lucide-react` namespace import, which pulled
// the whole icon set into every route rendering a status. The map replacing it
// is only correct if every slug the admin picker offers still resolves.
describe("getStatusIcon", () => {
  it("resolves every slug the admin picker offers", () => {
    for (const { slug, Icon } of STATUS_ICON_OPTIONS) {
      expect(getStatusIcon(slug)).toBe(Icon);
    }
  });

  it("resolves ShieldOff, the slug the built-in balancer 'Excluded' seed uses", () => {
    // Pinned on its own so dropping it from the picker list fails here instead
    // of silently turning the seeded status into BadgeHelp.
    expect(getStatusIcon("ShieldOff")).toBe(ShieldOff);
  });

  it("falls back to BadgeHelp for a slug the backend accepts but we do not bundle", () => {
    expect(getStatusIcon("Aperture")).toBe(BadgeHelp);
    expect(getStatusIcon("constructor")).toBe(BadgeHelp);
    expect(getStatusIcon("")).toBe(BadgeHelp);
    expect(getStatusIcon(null)).toBe(BadgeHelp);
    expect(getStatusIcon(undefined)).toBe(BadgeHelp);
  });
});
