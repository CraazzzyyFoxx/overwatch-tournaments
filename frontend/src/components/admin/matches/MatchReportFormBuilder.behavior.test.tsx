// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MatchReportFormBuilder } from "@/components/admin/matches/MatchReportFormBuilder";
import type { MatchReportForm } from "@/types/encounter.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getReportForm = vi.fn();
const saveReportForm = vi.fn();

vi.mock("@/services/report-form.service", () => ({
  default: {
    getReportForm: (...args: unknown[]) => getReportForm(...args),
    saveReportForm: (...args: unknown[]) => saveReportForm(...args)
  }
}));

// Labels come through as their message keys, so the assertions below read as the
// keys the component is contracted to use.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

// The `SaveBar` asks for a router to finish a navigation its discard prompt held back.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

async function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  await act(async () => {
    await promise;
  });
}

async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await tick();
  }
  throw new Error(`timed out waiting for ${what}`);
}

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  await tick();
  return container;
}

// Radix selects open on `pointerdown` and pick an option on `click`; both are sent.
async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    element!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await tick();
}

/** Opens the select labelled `label` and picks the option reading `option`. */
async function choose(scope: ParentNode, label: string, option: string) {
  await click(controlsLabelled(scope, label)[0]);
  await click(
    Array.from(document.querySelectorAll('[role="option"]')).find(
      (element) => element.textContent?.trim() === option
    )
  );
}

// React overrides the input's own `value` setter to track changes; assigning
// through it makes React think nothing changed, so write via the prototype.
const nativeValueSetter = Object.getOwnPropertyDescriptor(
  HTMLInputElement.prototype,
  "value"
)?.set;

async function type(input: Element | null | undefined, value: string) {
  expect(input).toBeTruthy();
  await act(async () => {
    nativeValueSetter?.call(input, value);
    input!.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await tick();
}

function button(scope: ParentNode, text: string) {
  return Array.from(scope.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

/**
 * Every control labelled `text`, resolved through `htmlFor` rather than DOM
 * position: Radix renders switches as buttons, so a wrapping label would not
 * associate and a positional lookup would silently follow a layout change.
 */
function controlsLabelled(scope: ParentNode, text: string): HTMLElement[] {
  return Array.from(scope.querySelectorAll("label"))
    .filter((label) => label.textContent?.trim() === text)
    .map((label) => scope.querySelector<HTMLElement>(`[id="${label.getAttribute("for")}"]`))
    .filter((element): element is HTMLElement => element !== null);
}

function form(overrides: Partial<MatchReportForm> = {}): MatchReportForm {
  return {
    tournament_id: 7,
    built_in_fields: {
      closeness: { enabled: true, required: true },
      map_codes: { enabled: true, required: false },
      comment: { enabled: true, required: false }
    },
    custom_fields: [],
    ...overrides
  };
}

describe("MatchReportFormBuilder", () => {
  beforeEach(() => {
    getReportForm.mockReset();
    saveReportForm.mockReset();
    getReportForm.mockResolvedValue(form());
    saveReportForm.mockImplementation(async () => form());
    document.body.innerHTML = "";
  });

  it("turns a field off without dropping its required rule", async () => {
    // "Off" hides the field from captains; the rule the organizer set must
    // survive in the saved config, or switching the field back on later
    // silently downgrades it.
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => button(container, "addField"), "the builder");

    // closeness ships enabled + required.
    expect(controlsLabelled(container, "fields.closeness")[0].textContent).toContain("modes.required");

    await choose(container, "fields.closeness", "modes.off");
    expect(controlsLabelled(container, "fields.closeness")[0].textContent).toContain("modes.off");

    await click(button(container, "save"));
    expect(saveReportForm).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        built_in_fields: expect.objectContaining({ closeness: { enabled: false, required: true } })
      })
    );
  });

  it("slugs a new field's key from its label until the key is edited by hand", async () => {
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => button(container, "addField"), "the add button");
    expect(container.textContent).toContain("noCustomFields");

    await click(button(container, "addField"));
    const label = () => controlsLabelled(container, "labelLabel")[0] as HTMLInputElement;
    const key = () => controlsLabelled(container, "keyLabel")[0] as HTMLInputElement;

    await type(label(), "Coach Notes 2!");
    expect(key().value).toBe("coach_notes_2");

    // Hand-editing the key ends the coupling: the key is the storage address of
    // every answer, so a later label tweak must not move it.
    await type(key(), "coach_debrief");
    await type(label(), "Coach debrief notes");
    expect(key().value).toBe("coach_debrief");
  });

  it("blocks Save on a duplicate key and says which rule broke", async () => {
    getReportForm.mockResolvedValue(
      form({
        custom_fields: [
          { key: "vod", label: "VOD link", type: "text", required: false, placeholder: null },
          { key: "notes", label: "Notes", type: "text", required: false, placeholder: null }
        ]
      })
    );
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => controlsLabelled(container, "keyLabel").length === 2, "both rows");

    const secondKey = controlsLabelled(container, "keyLabel")[1] as HTMLInputElement;
    await type(secondKey, "vod");

    // The reason is text in the save bar, not a red border, and saving sends nothing.
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("errors.keyDuplicate");
    await click(button(container, "save"));
    expect(saveReportForm).not.toHaveBeenCalled();

    await type(secondKey, "match_notes");
    expect(container.textContent).not.toContain("errors.keyDuplicate");
    await click(button(container, "save"));
    expect(saveReportForm).toHaveBeenCalledTimes(1);
  });

  it("blocks Save on a field with no label", async () => {
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => button(container, "addField"), "the add button");

    await click(button(container, "addField"));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("errors.labelRequired");
    await click(button(container, "save"));
    expect(saveReportForm).not.toHaveBeenCalled();
  });

  it("saves the built-in choices and the custom text fields together", async () => {
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => button(container, "addField"), "the builder");

    // Nothing edited yet: no save bar, nothing to persist.
    expect(button(container, "save")).toBeUndefined();

    await choose(container, "fields.comment", "modes.required");
    await click(button(container, "addField"));
    await type(controlsLabelled(container, "labelLabel")[0], "Coach notes");
    await type(controlsLabelled(container, "placeholderLabel")[0], "  Anything else  ");

    await click(button(container, "save"));

    expect(saveReportForm).toHaveBeenCalledWith(7, {
      built_in_fields: {
        closeness: { enabled: true, required: true },
        map_codes: { enabled: true, required: false },
        comment: { enabled: true, required: true }
      },
      custom_fields: [
        {
          key: "coach_notes",
          label: "Coach notes",
          type: "text",
          required: false,
          placeholder: "Anything else"
        }
      ]
    });
  });

  it("stops at the 20-field cap and says why the add button is dead", async () => {
    getReportForm.mockResolvedValue(
      form({
        custom_fields: Array.from({ length: 20 }, (_, index) => ({
          key: `field_${index}`,
          label: `Field ${index}`,
          type: "text" as const,
          required: false,
          placeholder: null
        }))
      })
    );
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    const add = await waitFor(() => button(container, "addField"), "the add button");

    expect(add.hasAttribute("disabled")).toBe(true);
    const noticeId = add.getAttribute("aria-describedby");
    expect(container.querySelector(`[id="${noticeId}"]`)?.textContent).toContain(
      "maxFieldsReached"
    );
  });

  it("reports a failed load instead of offering the defaults as saved config", async () => {
    getReportForm.mockRejectedValue(new Error("boom"));
    const container = await mount(<MatchReportFormBuilder tournamentId={7} />);
    await waitFor(() => container.textContent?.includes("loadError"), "the load error");

    expect(button(container, "save")).toBeUndefined();
    expect(button(container, "addField")).toBeUndefined();
  });
});
