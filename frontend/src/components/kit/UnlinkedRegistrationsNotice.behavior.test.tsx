// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnlinkedRegistrationsNotice, countUnlinkedRegistrations } from "./UnlinkedRegistrationsNotice";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: { count: number }) => `${key}:${values?.count}`
}));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

const containers: HTMLElement[] = [];
afterEach(() => containers.splice(0).forEach((node) => node.remove()));

function render(count: number) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  containers.push(container);
  act(() => createRoot(container).render(<UnlinkedRegistrationsNotice count={count} />));
  return container;
}

describe("UnlinkedRegistrationsNotice", () => {
  it("counts the live registrations with no workspace member", () => {
    expect(
      countUnlinkedRegistrations([
        { workspace_member_id: null, deleted_at: null },
        { workspace_member_id: 4, deleted_at: null },
        { workspace_member_id: null, deleted_at: "2026-11-05T00:00:00Z" }
      ])
    ).toBe(1);
  });

  it("names the count when some registrations are excluded", () => {
    expect(render(3).textContent).toBe("message:3");
  });

  it("renders nothing when every registration is linked", () => {
    expect(render(0).textContent).toBe("");
  });
});
