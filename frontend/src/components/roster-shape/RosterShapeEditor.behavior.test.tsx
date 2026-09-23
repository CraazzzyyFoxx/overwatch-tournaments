// @vitest-environment happy-dom
//
// The model tests cover the state machine; this covers what the model cannot see:
// that every message key the editor asks for actually exists (next-intl renders
// the raw key path otherwise, which reads as a broken page), and that the three
// states an admin can land in — inheriting, overriding, locked — each render the
// thing that state is supposed to tell them.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RosterShape, RosterSlotMap } from "@/lib/roster/shape";

import { RosterShapeEditor } from "./RosterShapeEditor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function mount(props: {
  value: RosterSlotMap | null;
  effective: RosterShape | null;
  locked?: boolean;
}) {
  const host = document.createElement("div");
  document.body.append(host);
  act(() => {
    createRoot(host).render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <RosterShapeEditor onChange={() => {}} {...props} />
      </NextIntlClientProvider>
    );
  });
  return host;
}

const shape = (over: Partial<RosterShape> = {}): RosterShape => ({
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 4,
  source: "workspace",
  ...over
});

/** Preview rows, stripped of the leading position number. */
function previewRows(host: HTMLElement): string[] {
  return [...host.querySelectorAll("ol li")].map((li) => li.textContent?.replace(/^\d+/, "") ?? "");
}

describe("RosterShapeEditor", () => {
  it("names the inherited shape and its source instead of passing it off as its own", () => {
    const host = mount({ value: null, effective: shape() });

    expect(host.textContent).toContain(
      "Inherited from the workspace default: 1 Tank · 2 Damage · 2 Support"
    );
    // Totals come off the server shape.
    expect(host.textContent).toContain("5 slots");
    expect(previewRows(host)).toEqual(["Tank", "Damage", "Damage", "Support", "Support"]);
    // Nothing to edit while inheriting.
    expect(host.querySelectorAll("input")).toHaveLength(0);
  });

  it("previews a role-free shape as one row per flex slot, which is the point of the preview", () => {
    const host = mount({
      value: { tank: 1, flex: 5 },
      effective: shape({
        slots: { tank: 1, flex: 5 },
        team_size: 6,
        flex_slots: 5,
        draft_rounds: 5,
        source: "tournament"
      })
    });

    expect(host.textContent).toContain("pins its own shape");
    expect(host.textContent).toContain("6 slots");
    expect(previewRows(host)).toEqual(["Tank", "Flex", "Flex", "Flex", "Flex", "Flex"]);
    // One stepper per slot code.
    expect(host.querySelectorAll("input")).toHaveLength(4);
  });

  it("accepts a one-slot team as a plain 1v1 format", () => {
    const host = mount({ value: { flex: 1 }, effective: shape({ slots: { flex: 1 }, team_size: 1 }) });

    expect(host.querySelector("[role=alert]")).toBeNull();
    expect(host.textContent).toContain("1 slot");
  });

  it("says a total is out of range inline rather than letting the save find out", () => {
    const host = mount({ value: { tank: 6, flex: 7 }, effective: shape() });

    expect(host.querySelector("[role=alert]")?.textContent).toContain("at most 12 slots");
  });

  it("disables every control and explains why while a draft session is in flight", () => {
    const host = mount({
      value: { flex: 6 },
      effective: shape({ source: "tournament" }),
      locked: true
    });

    expect(host.textContent).toContain("draft session has already been created");
    expect([...host.querySelectorAll("input")].every((input) => input.disabled)).toBe(true);
  });
});
