import { afterAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act, type ReactNode } from "react";

import { ApiError } from "@/lib/api-error";
import type { FormField, FormSchema } from "@/types/forms.types";
import type { RegistrationForm } from "@/types/registration.types";

const testWindow = new Window({ url: "http://localhost:3000/", width: 900, height: 900 });
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();

/** What `registrationService.register` throws on the next submit. */
let rejection: unknown = null;

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
mock.module("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => ({ user: null }) }));
mock.module("@/services/me.service", () => ({ default: { getSocialAccounts: async () => null } }));
mock.module("@/services/hero.service", () => ({ default: { getAll: async () => ({ results: [] }) } }));
mock.module("@/services/registration.service", () => ({
  default: {
    getMySubscriptionStatus: async () => ({ required: false, verdicts: {} }),
    register: async () => {
      throw rejection;
    },
  },
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
const RegistrationWizard = (await import("./RegistrationWizard")).default;

function field(overrides: Partial<FormField> & Pick<FormField, "key" | "kind">): FormField {
  return {
    label: overrides.key,
    required: false,
    visibility: "public",
    params: {},
    ...overrides,
  };
}

/** One step, one free-text question — enough to reach the submit button. */
const SCHEMA: FormSchema = {
  schema_version: 1,
  sections: [
    { key: "details", title: "Details", fields: [field({ key: "public_notes", kind: "builtin" })] },
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

/** Mount the wizard and press its last button (Submit on a single-step form). */
async function submitWith(error: unknown) {
  rejection = error;
  container = testWindow.document.createElement("div");
  testWindow.document.body.appendChild(container);
  root = createRoot(container as unknown as Element);
  act(() => {
    root.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}
      >
        <RegistrationWizard workspaceId={3} tournamentId={7} form={FORM} onClose={() => {}} />
      </QueryClientProvider>,
    );
  });
  const buttons = container.querySelectorAll("button");
  await act(async () => {
    buttons[buttons.length - 1].dispatchEvent(
      new testWindow.MouseEvent("click", { bubbles: true }) as unknown as Event,
    );
  });
}

describe("RegistrationWizard", () => {
  it("leaves the banner to the form when the rejection names a field", async () => {
    // react-query runs a mutation's `onError` even though `RegistrationSchemaForm`
    // also catches the rejected `mutateAsync`, so an unguarded banner showed a
    // generic copy of the very message already rendered under the control.
    await submitWith(
      new ApiError(422, [{ msg: "Not a BattleTag", code: "invalid_format", field: "public_notes" }]),
    );

    // The wizard's own banner — the form's inline messages are `<p role="alert">`.
    expect(container.querySelector('div[role="alert"]')).toBeNull();
    // …and the form did render it, so the rejection is not lost.
    expect(container.querySelector('[aria-invalid="true"]')).not.toBeNull();
  });

  it("still shows the banner for a failure that names no field", async () => {
    await submitWith(new ApiError(500, [{ msg: "Upstream exploded", code: "unknown" }]));

    expect(container.querySelector('div[role="alert"]')?.textContent).toBe("Upstream exploded");
  });
});

afterAll(() => {
  act(() => root.unmount());
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});
