// @vitest-environment happy-dom
//
// Two claims about the workspace templates screen, both about work that cannot
// be recovered from the UI:
//
// 1. Deleting a template asks first. A template is shared by every tournament
//    in the workspace and there is no restore.
// 2. Opening another template while the questions on screen are unsaved asks
//    first, and only switches once the organizer agrees to lose them.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";

import Page from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as never;
for (const [name, value] of Object.entries({
  hasPointerCapture: () => false,
  setPointerCapture: () => undefined,
  releasePointerCapture: () => undefined,
  scrollIntoView: () => undefined
})) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, { value, writable: true });
  }
}

const listTemplates = vi.fn();
const removeTemplate = vi.fn();
const updateTemplate = vi.fn();

vi.mock("@/services/registration-form-templates.service", () => ({
  default: {
    list: (...args: unknown[]) => listTemplates(...args),
    create: vi.fn(),
    update: (...args: unknown[]) => updateTemplate(...args),
    remove: (...args: unknown[]) => removeTemplate(...args)
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: { getPlayerSubRoles: vi.fn().mockResolvedValue([]) }
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/settings/registration-forms",
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams("")
}));

function template(id: number, name: string, sectionTitle: string) {
  return {
    id,
    workspace_id: 1,
    name,
    updated_at: "2026-01-01",
    form_schema: {
      schema_version: 1,
      sections: [
        {
          key: "accounts",
          title: sectionTitle,
          description: null,
          fields: [
            {
              key: "battle_tag",
              kind: "builtin",
              label: null,
              help: null,
              placeholder: null,
              required: true,
              visibility: "public",
              options: null,
              validation: null,
              params: {},
            }
          ]
        }
      ]
    }
  };
}

let container: HTMLDivElement;
let root: Root;

async function settle(times = 8) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <Page />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

/** Everything in the document, portalled dialogs included. */
function button(text: string): HTMLElement {
  const found = [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) => (element.textContent ?? "").trim() === text
  );
  if (found.length === 0) throw new Error(`no button named "${text}"`);
  return found[0];
}

function byLabel(label: string): HTMLElement {
  const found = document.querySelector<HTMLElement>(`[aria-label="${label}"]`);
  if (!found) throw new Error(`no control labelled "${label}"`);
  return found;
}

function labelled<T extends HTMLElement>(text: string): T {
  const node = [...document.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === text
  );
  const id = node?.getAttribute("for");
  const control = id ? document.getElementById(id) : null;
  if (!control) throw new Error(`no control labelled "${text}"`);
  return control as T;
}

function confirmDialog(): HTMLElement | null {
  return document.body.querySelector("[role='alertdialog']");
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  listTemplates.mockResolvedValue([
    template(11, "Open cup", "Who are you"),
    template(12, "Closed cup", "Roster check")
  ]);
  removeTemplate.mockResolvedValue(undefined);
  updateTemplate.mockResolvedValue(template(11, "Open cup", "Who are you"));
});

describe("workspace registration form templates", () => {
  it("asks before deleting a workspace-shared template", async () => {
    await mount();

    await click(byLabel("Delete Open cup"));
    expect(removeTemplate).not.toHaveBeenCalled();
    expect(confirmDialog()?.textContent ?? "").toContain("Open cup");

    await click(button("Delete template"));
    await settle();
    expect(removeTemplate).toHaveBeenCalledWith(1, 11);
  });

  it("asks before dropping unsaved questions for another template", async () => {
    await mount();

    await click(button("Edit questions"));
    // Dirty the draft: open the one question and flip Required.
    await click(button("BattleTagbattle_tagRequired"));
    await click(labelled("Required"));

    // The second template's "Edit questions" — the first row now reads "Editing".
    await click(button("Edit questions"));
    expect(confirmDialog()).not.toBeNull();
    expect(container.textContent).toContain("Who are you");
    expect(container.textContent).not.toContain("Roster check");

    await click(button("Discard and switch"));
    await settle();
    expect(container.textContent).toContain("Roster check");
  });
});
