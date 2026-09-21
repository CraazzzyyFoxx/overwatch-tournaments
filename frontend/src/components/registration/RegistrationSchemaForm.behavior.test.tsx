import { afterAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act, type ReactNode } from "react";

import type { FormField, FormSchema } from "@/types/forms.types";
import en from "@/i18n/messages/en.json";
import { IDENTITY_PROVIDERS, identityKey } from "@/lib/forms/builtin-keys";
import type { RegistrationForm } from "@/types/registration.types";

const testWindow = new Window({ url: "http://localhost:3000/", width: 900, height: 900 });
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => Object.assign((key: string) => key, { has: () => true }),
}));
// Radix portals and pointer measurement do not work under happy-dom; these two
// primitives are stood in by the contracts the form actually uses.
mock.module("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children, ...rest }: { children: ReactNode }) => (
    <button type="button" {...rest}>
      {children}
    </button>
  ),
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));
mock.module("@/components/ui/switch", () => ({
  Switch: () => <button type="button" role="switch" aria-checked="false" />,
}));
mock.module("@/services/hero.service", () => ({ default: { getAll: async () => ({ results: [] }) } }));
mock.module("@/services/registration.service", () => ({
  default: { getMySubscriptionStatus: async () => ({ required: false, verdicts: {} }) },
}));
mock.module("@/services/rbac.service", () => ({
  rbacService: { listOAuthConnections: async () => ({ results: [] }) },
}));
mock.module("@/stores/account-settings-modal.store", () => ({
  useAccountSettingsModalStore: (select: (state: { open: () => void }) => unknown) =>
    select({ open: () => {} }),
}));
mock.module("@/lib/notify", () => ({ notify: { error: () => {} } }));

for (const [key, value] of Object.entries({
  window: testWindow,
  document: testWindow.document,
  navigator: testWindow.navigator,
  HTMLElement: testWindow.HTMLElement,
  Event: testWindow.Event,
  Node: testWindow.Node,
  MutationObserver: testWindow.MutationObserver,
  getComputedStyle: testWindow.getComputedStyle.bind(testWindow),
  requestAnimationFrame: testWindow.requestAnimationFrame.bind(testWindow),
  cancelAnimationFrame: testWindow.cancelAnimationFrame.bind(testWindow),
  IS_REACT_ACT_ENVIRONMENT: true,
})) {
  previousGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, value, writable: true });
}

// `mock.module` must be registered before the module graph under test loads.
const { createRoot } = await import("react-dom/client");
const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
const RegistrationSchemaForm = (await import("./RegistrationSchemaForm")).default;

function field(overrides: Partial<FormField> & Pick<FormField, "key" | "kind">): FormField {
  return {
    label: overrides.key,
    required: false,
    visibility: "public",
    params: {},
    show_in_draft: false,
    ...overrides,
  };
}

/** One step, the two notes builtins — the `public_notes`/`organizer_notes` pair. */
const SCHEMA: FormSchema = {
  schema_version: 1,
  sections: [
    {
      key: "details",
      title: "Details",
      fields: [
        field({ key: "public_notes", kind: "builtin" }),
        field({ key: "organizer_notes", kind: "builtin", visibility: "organizers" }),
      ],
    },
  ],
};

const FORM = {
  id: 1,
  tournament_id: 7,
  workspace_id: 3,
  is_open: true,
  form_schema: SCHEMA,
  version_id: 42,
  version_number: 2,
  subrole_catalog: {},
} as unknown as RegistrationForm;

let container = testWindow.document.createElement("div");
let root = createRoot(container as unknown as Element);

function type(element: Element, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    testWindow.HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  act(() => {
    setter?.call(element, value);
    element.dispatchEvent(new testWindow.Event("input", { bubbles: true }) as unknown as Event);
  });
}

describe("RegistrationSchemaForm", () => {
  it("asks the registrant organizers-only questions and submits their answers", async () => {
    // `visibility` decides who READS an answer, not who is asked for it:
    // `organizer_notes` is the player-writes/organizer-reads half of the pair,
    // so hiding it from the registrant would make it unanswerable by anyone.
    let submitted: { answers: Record<string, unknown> } | null = null;

    container = testWindow.document.createElement("div");
    testWindow.document.body.appendChild(container);
    root = createRoot(container as unknown as Element);
    act(() => {
      root.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <RegistrationSchemaForm
            mode="public"
            form={FORM}
            tournamentId={7}
            onSubmit={async (input) => {
              submitted = input;
            }}
            onCancel={() => {}}
          />
        </QueryClientProvider>,
      );
    });

    const boxes = container.querySelectorAll("textarea");
    expect(boxes.length).toBe(2);
    // …and the registrant is told the answer is not published.
    expect(container.textContent).toContain("organizersOnly");

    type(boxes[1], "for the organizers only");

    const submit = container.querySelectorAll("button")[
      container.querySelectorAll("button").length - 1
    ];
    await act(async () => {
      submit.dispatchEvent(new testWindow.MouseEvent("click", { bubbles: true }) as unknown as Event);
    });

    expect(submitted).not.toBeNull();
    expect(submitted?.answers.organizer_notes).toBe("for the organizers only");
    expect(submitted?.answers.public_notes).toBe(null);
  });

  it("words every identity question, including the providers with no brand icon", async () => {
    // A builtin carries no label of its own, so the renderer must have copy for
    // each provider `IDENTITY_PROVIDERS` offers — otherwise the builder lets an
    // organizer add VK and the registrant is asked "identity_vk".
    container = testWindow.document.createElement("div");
    testWindow.document.body.appendChild(container);
    root = createRoot(container as unknown as Element);
    act(() => {
      root.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <RegistrationSchemaForm
            mode="public"
            form={
              {
                ...FORM,
                form_schema: {
                  schema_version: 1,
                  sections: [
                    {
                      key: "accounts",
                      fields: IDENTITY_PROVIDERS.map((provider) =>
                        field({ key: identityKey(provider), kind: "builtin", label: null }),
                      ),
                    },
                  ],
                },
              } as unknown as RegistrationForm
            }
            tournamentId={7}
            onSubmit={async () => {}}
            onCancel={() => {}}
          />
        </QueryClientProvider>,
      );
    });

    for (const provider of IDENTITY_PROVIDERS) {
      // `useTranslations` is mocked to echo the key, so this asserts WHICH
      // message the field asks for…
      expect(container.textContent).toContain(`registration.accounts.${provider}`);
      expect(container.textContent).not.toContain(identityKey(provider));
      // …and this asserts the catalogue actually has it.
      expect(en.registration.accounts[provider as keyof typeof en.registration.accounts]).toBeTruthy();
    }
  });

  it("keeps the answers a registrant typed when the form is closed, until it submits", async () => {
    // Closing the dialog unmounts the form, and an accidental Esc looks exactly
    // like Cancel from in here — so the answer document has to outlive the mount.
    testWindow.localStorage.clear();
    let submitted = false;

    const mount = () => {
      container = testWindow.document.createElement("div");
      testWindow.document.body.appendChild(container);
      root = createRoot(container as unknown as Element);
      act(() => {
        root.render(
          <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
            <RegistrationSchemaForm
              mode="public"
              form={FORM}
              tournamentId={7}
              onSubmit={async () => {
                submitted = true;
              }}
              onCancel={() => {}}
            />
          </QueryClientProvider>,
        );
      });
    };

    mount();
    type(container.querySelectorAll("textarea")[0], "half an answer");
    act(() => root.unmount());

    mount();
    expect(container.querySelectorAll("textarea")[0].value).toBe("half an answer");

    const buttons = container.querySelectorAll("button");
    await act(async () => {
      buttons[buttons.length - 1].dispatchEvent(
        new testWindow.MouseEvent("click", { bubbles: true }) as unknown as Event,
      );
    });
    expect(submitted).toBe(true);
    expect(testWindow.localStorage.getItem("aqt:registration-draft:7")).toBeNull();

    // …and a fresh registration after that one opens empty.
    act(() => root.unmount());
    mount();
    expect(container.querySelectorAll("textarea")[0].value).toBe("");
  });
});

afterAll(() => {
  act(() => root.unmount());
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});
