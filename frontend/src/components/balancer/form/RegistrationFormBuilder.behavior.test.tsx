// @vitest-environment happy-dom
//
// Two claims about the schema builder.
//
// 1. What the organizer assembles on screen is what the upsert sends: a new
//    section, a custom `select` with two options and a `visible_when` pointing
//    at an EARLIER builtin come back as one `form_schema` document — including
//    the answer key derived from the label, which is what every stored answer
//    is filed under and the one thing a rename must never change afterwards.
// 2. Loading a template replaces the draft only after the confirmation. The
//    dialog's list is a browser; picking a row must not overwrite the questions
//    behind it, because there is no undo for "I clicked the wrong template".
// 3. A `schema_invalid` rejection lands on the question it names. The server
//    reports a schema PATH; a toast saying "sections[0].fields[1].visible_when"
//    is not something an organizer can act on, so it is resolved to the field
//    and shown under its settings instead.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api-error";
import { notify } from "@/lib/notify";
import type { FormSchema } from "@/types/forms.types";

import RegistrationFormBuilder from "./RegistrationFormBuilder";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Radix's menus and selects reach for layout APIs happy-dom does not implement.
// Without these the trigger throws before anything ever opens.
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

const getRegistrationForm = vi.fn();
const upsertRegistrationForm = vi.fn();
const listTemplates = vi.fn();

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getRegistrationForm: (...args: unknown[]) => getRegistrationForm(...args),
    upsertRegistrationForm: (...args: unknown[]) => upsertRegistrationForm(...args)
  }
}));

vi.mock("@/services/registration-form-templates.service", () => ({
  default: {
    list: (...args: unknown[]) => listTemplates(...args),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    apply: vi.fn(),
    saveFromForm: vi.fn()
  }
}));

vi.mock("@/services/admin.service", () => ({
  default: { getPlayerSubRoles: vi.fn().mockResolvedValue([]) }
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));

vi.mock("@/lib/notify", () => ({
  notify: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    apiError: vi.fn()
  }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/tournaments/1/registration/form",
  useParams: () => ({ id: "1" }),
  useSearchParams: () => new URLSearchParams("")
}));

function builtin(key: string, required = false) {
  return {
    key,
    kind: "builtin" as const,
    label: null,
    help: null,
    placeholder: null,
    required,
    visibility: "public" as const,
    options: null,
    validation: null,
    params: {},
    show_in_draft: false
  };
}

const SERVER_SCHEMA: FormSchema = {
  schema_version: 1,
  sections: [
    {
      key: "accounts",
      title: null,
      description: null,
      fields: [builtin("battle_tag", true), builtin("stream_pov")]
    }
  ]
};

const TEMPLATE_SCHEMA: FormSchema = {
  schema_version: 1,
  sections: [
    { key: "identity", title: "Who are you", description: null, fields: [builtin("battle_tag", true)] }
  ]
};

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
          <RegistrationFormBuilder tournamentId={1} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

/** Types into a controlled field the way React hears it. */
async function type(field: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    field instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  await act(async () => {
    setter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

/** React delegates `onBlur` from `focusout`, so that is what commits the key. */
async function blur(element: Element) {
  await act(async () => {
    element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });
  await settle(2);
}

/** Everything in the document, portalled menus and dialogs included. */
function byRole(role: string, text: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(`[role="${role}"]`)].filter(
    (element) => (element.textContent ?? "").trim() === text
  );
}

function button(text: string): HTMLElement {
  const found = [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) => (element.textContent ?? "").trim() === text
  );
  if (found.length === 0) throw new Error(`no button named "${text}"`);
  return found[0];
}

/** The control a visible `<label>` names. */
function labelled<T extends HTMLElement>(text: string): T {
  const label = [...document.querySelectorAll("label")].find(
    (element) => (element.textContent ?? "").trim() === text
  );
  const id = label?.getAttribute("for");
  const control = id ? document.getElementById(id) : null;
  if (!control) throw new Error(`no control labelled "${text}"`);
  return control as T;
}

/** Opens the Select labelled `text` and picks `option` from its listbox. */
async function choose(text: string, option: string) {
  await click(labelled(text));
  const items = byRole("option", option);
  if (items.length === 0) throw new Error(`no option named "${option}"`);
  await click(items[0]);
}

/** Opens a dropdown menu and activates the item with this label. */
async function menuItem(trigger: string, item: string) {
  await click(button(trigger));
  const items = byRole("menuitem", item);
  if (items.length === 0) throw new Error(`no menu item named "${item}"`);
  await click(items[0]);
}

function railText(): string {
  return container.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  getRegistrationForm.mockResolvedValue({
    id: 7,
    tournament_id: 1,
    workspace_id: 1,
    form_schema: SERVER_SCHEMA,
    version_id: 3,
    version_number: 2,
    stale_registrations: 0,
    auto_approve: false,
    require_open_profile: false,
    open_profile_scope: "main",
    show_ranks: false,
    hide_registrations: false,
    max_participants: null,
    max_substitutes: 0,
    subscription_scope: "player",
    subscription_stage: "check_in",
    require_subscription: false,
    team_rank_min: null,
    team_rank_max: null,
    team_max_rank_spread: null,
    team_unique_identity: false,
    team_require_discord_guild: false
  });
  upsertRegistrationForm.mockResolvedValue({
    id: 7,
    form_schema: SERVER_SCHEMA,
    version_id: 4,
    version_number: 3,
    stale_registrations: 2
  });
  listTemplates.mockResolvedValue([
    { id: 11, workspace_id: 1, name: "Open cup", form_schema: TEMPLATE_SCHEMA, updated_at: "2026-01-01" }
  ]);
});

describe("registration form builder", () => {
  it("sends the assembled schema: new section, custom select, earlier-field condition", async () => {
    await mount();

    await click(button("Add section"));
    await menuItem("Add question", "Select one");

    await type(labelled<HTMLInputElement>("Label"), "Stream link");
    await blur(labelled<HTMLInputElement>("Label"));
    await type(labelled<HTMLTextAreaElement>("Options (one per line)"), "Twitch\nYouTube");
    await choose("Show only when", "Stream POV");

    await click(button("Save changes"));
    await settle();

    expect(upsertRegistrationForm).toHaveBeenCalledTimes(1);
    const [tournamentId, body] = upsertRegistrationForm.mock.calls[0];
    expect(tournamentId).toBe(1);
    expect(body.form_schema).toEqual({
      schema_version: 1,
      sections: [
        {
          key: "accounts",
          title: null,
          description: null,
          fields: [
            { ...builtin("battle_tag", true) },
            { ...builtin("stream_pov") }
          ]
        },
        {
          key: "section",
          title: null,
          description: null,
          fields: [
            {
              // Derived from the label once, then locked.
              key: "stream_link",
              kind: "select",
              label: "Stream link",
              help: null,
              placeholder: null,
              required: false,
              visibility: "public",
              options: ["Twitch", "YouTube"],
              validation: null,
              params: {},
              show_in_draft: false,
              visible_when: { field: "stream_pov", op: "truthy" }
            }
          ]
        }
      ]
    });
  });

  it("replaces the draft with a template only after the confirmation", async () => {
    await mount();

    await menuItem("Templates", "Load a template…");
    await settle();

    // The dialog lists the workspace's templates; picking a row is browsing.
    await click(button("Open cup1 step"));
    expect(railText()).not.toContain("Who are you");

    await click(button("Replace the questions"));
    await settle();

    expect(railText()).toContain("Who are you");
  });

  it("files a schema_invalid rejection on the question its path names", async () => {
    upsertRegistrationForm.mockRejectedValueOnce(
      new ApiError(422, [
        {
          msg: "sections[0].fields[1].visible_when: must reference an earlier field",
          code: "schema_invalid",
          field: "sections[0].fields[1].visible_when"
        }
      ])
    );
    await mount();

    // `stream_pov` is the field that path names; open it and dirty the form so
    // the save bar is reachable.
    await click(button("Stream POVstream_pov"));
    await click(labelled("Required"));
    await click(button("Save changes"));
    await settle();

    const panel = container.textContent ?? "";
    expect(panel).toContain("sections[0].fields[1].visible_when");
    expect(panel).toContain(en.forms.errors.schema_invalid);
    // Not a toast: a rejection that names a field belongs under that field.
    expect(notify.error).not.toHaveBeenCalled();
  });
});
