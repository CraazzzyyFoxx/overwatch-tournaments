// @vitest-environment happy-dom
//
// The message-parity test only proves en.json and ru.json agree with each
// other. It cannot see a key the page *asks* for and neither file defines —
// next-intl then renders the raw key path, which reads as a broken page. This
// mounts the whole builder in both locales, walks its surfaces (the section
// rail, the add-question menu, a field's settings panel with the `roles` params
// editor, the preview) and fails on any unresolved lookup.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { FormSchema } from "@/types/forms.types";

import RegistrationFormBuilder from "./RegistrationFormBuilder";

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

/** `vi.mock` factories are hoisted above every binding in the module, so the
 *  schema is built inside the one that needs it. */
function schemaFixture(): FormSchema {
  const builtin = (key: string, required = false) => ({
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
  });
  return {
    schema_version: 1,
    sections: [
      {
        key: "accounts",
        title: null,
        description: null,
        fields: [builtin("battle_tag", true), builtin("identity_discord")]
      },
      { key: "roles", title: null, description: null, fields: [builtin("roles")] }
    ]
  };
}

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getRegistrationForm: vi.fn().mockResolvedValue({
      id: 1,
      tournament_id: 1,
      workspace_id: 1,
      form_schema: schemaFixture(),
      version_id: 2,
      version_number: 1,
      stale_registrations: 3,
      auto_approve: false,
      require_open_profile: true,
      open_profile_scope: "all",
      require_subscription: true,
      show_ranks: false
    }),
    upsertRegistrationForm: vi.fn()
  }
}));
vi.mock("@/services/registration-form-templates.service", () => ({
  default: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    apply: vi.fn(),
    saveFromForm: vi.fn()
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getPlayerSubRoles: vi
      .fn()
      .mockResolvedValue([{ id: 1, role: "tank", slug: "main_tank", label: "Main Tank" }])
  }
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/admin/tournaments/1/registration/form",
  useParams: () => ({ id: "1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() })
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

const MESSAGES = { en, ru } as const;

async function settle(times = 8) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/** Radix reads different halves of a press per primitive: menus and selects
 *  open on `pointerdown`, `Tabs` switches on `mousedown`. */
async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

async function renderPage(locale: "en" | "ru") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <RegistrationFormBuilder tournamentId={1} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return { container, root };
}

describe("admin registration form i18n", () => {
  for (const locale of ["en", "ru"] as const) {
    it(`renders every surface in ${locale} with no unresolved message keys`, async () => {
      const errors: unknown[][] = [];
      const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
        errors.push(args);
      });

      const { container, root } = await renderPage(locale);

      // The roles section, then its one question: that is where the params
      // editor with the sub-role catalog lives.
      const rail = [...container.querySelectorAll("button")].filter((node) =>
        (node.textContent ?? "").includes(MESSAGES[locale].registrationFormAdmin.builder.sectionFallback.replace("{index}", "2"))
      );
      await click(rail[0]);
      const rolesRow = [...container.querySelectorAll("button")].find((node) =>
        (node.textContent ?? "").includes(MESSAGES[locale].registrationFormAdmin.builtins.roles)
      );
      if (!rolesRow) throw new Error("the roles question is not listed");
      await click(rolesRow);

      // The preview renders the whole schema through the registration
      // renderers, which carry copy of their own.
      const tab = (label: string) =>
        [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(
          (node) => (node.textContent ?? "").trim() === label
        );
      const preview = tab(MESSAGES[locale].registrationFormAdmin.builder.previewTab);
      if (!preview) throw new Error("the preview tab is not rendered");
      await click(preview);
      const previewText = container.textContent ?? "";
      // Non-vacuous: the panel really switched before the key check runs.
      expect(previewText).toContain(MESSAGES[locale].registrationFormAdmin.builder.previewNote);
      expect(previewText).not.toMatch(/registrationFormAdmin\./);

      const edit = tab(MESSAGES[locale].registrationFormAdmin.builder.editTab);
      if (!edit) throw new Error("the build tab is not rendered");
      await click(edit);

      // The add-question menu carries the builtin and custom-kind vocabularies.
      const addField = [...container.querySelectorAll("button")].find(
        (node) =>
          (node.textContent ?? "").trim() ===
          MESSAGES[locale].registrationFormAdmin.builder.addField
      );
      if (!addField) throw new Error("the add-question menu is not rendered");
      await click(addField);

      const text = (container.textContent ?? "") + (document.body.textContent ?? "");
      expect(text).not.toMatch(/registrationFormAdmin\./);
      expect(text).not.toMatch(/\bforms\.errors\./);
      expect(
        errors.filter((args) => /MISSING_MESSAGE|INSUFFICIENT_PATH|IntlError/.test(String(args[0])))
      ).toEqual([]);

      // Sanity: the localized copy actually differs per locale. The subscription
      // rule summary moved with the admission rules to `settings/admission`,
      // which has its own i18n test.
      expect(text).toContain(locale === "ru" ? "Саброли" : "Subroles");

      await act(async () => {
        root.unmount();
      });
      container.remove();
      document.body.innerHTML = "";
      spy.mockRestore();
    });
  }
});
