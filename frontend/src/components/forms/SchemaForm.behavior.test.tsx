import { afterAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act, useState, type ReactNode } from "react";

import type { Translate } from "@/lib/forms/form-errors";
import type { Answers, FormField, FormSchema } from "@/types/forms.types";

import type { FieldRendererContext } from "./types";

const testWindow = new Window({ url: "http://localhost:3000/", width: 720, height: 900 });
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
}));
// Radix portals and pointer measurement do not work under happy-dom. The two
// primitives `GenericField` reaches for are stood in by their own contracts:
// a `select` never opens in these cases, and the switch is a toggle button.
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
  Switch: ({
    checked,
    onCheckedChange,
    ...rest
  }: {
    checked?: boolean;
    onCheckedChange?: (next: boolean) => void;
  }) => (
    <button
      type="button"
      role="switch"
      aria-checked={checked ?? false}
      onClick={() => onCheckedChange?.(!checked)}
      {...rest}
    />
  ),
}));

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
const SchemaFormModule = await import("./SchemaForm");
const SchemaForm = SchemaFormModule.default;
const { schemaSteps } = SchemaFormModule;

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

/** Two sections. The second holds one field, gated on the first's checkbox. */
const SCHEMA: FormSchema = {
  schema_version: 1,
  sections: [
    {
      key: "main",
      title: "Main section",
      fields: [
        field({ key: "reveal", kind: "checkbox" }),
        field({ key: "vk", kind: "text", required: true }),
        // Optional, so it never wins the "first objection" race on an empty
        // form — it is here to prove a non-`required` rule still bites.
        field({ key: "pick", kind: "select", options: ["S", "M"] }),
      ],
    },
    {
      key: "extra",
      title: "Extra section",
      fields: [
        field({
          key: "note",
          kind: "text",
          visible_when: { field: "reveal", op: "truthy" },
        }),
      ],
    },
  ],
};

const CONTEXT: FieldRendererContext = {
  mode: "public",
  accounts: [],
  subroleCatalog: {},
  heroes: [],
  lockedRole: null,
  subscription: null,
  // The key-echo translator the whole suite uses: an error reads as its code.
  t: ((key: string) => key) as unknown as Translate,
};

let container = testWindow.document.createElement("div");
let root = createRoot(container as unknown as Element);

/** The step the harness stands on, published to the DOM so a blocked Next is
 *  observable without a side effect during render. */
const reachedStep = () =>
  Number(container.querySelector("[data-step]")?.getAttribute("data-step") ?? -1);

function Harness({
  serverErrors = {},
  initial = {},
  mode = "public",
}: {
  serverErrors?: Record<string, string>;
  initial?: Answers;
  mode?: "public" | "admin";
}) {
  const [answers, setAnswers] = useState<Answers>(initial);
  const [step, setStep] = useState(0);
  const [showErrors, setShowErrors] = useState(false);
  return (
    <>
      <span data-step={step} />
      <SchemaForm
        schema={SCHEMA}
        answers={answers}
        onChange={(key, value) => setAnswers((prev) => ({ ...prev, [key]: value }))}
        renderers={{}}
        context={{ ...CONTEXT, mode }}
        serverErrors={serverErrors}
        step={step}
        onStepChange={setStep}
        showErrors={showErrors}
        footer={({ isLast, stepError }) => (
          <button
            type="button"
            data-next
            onClick={() => {
              if (stepError) {
                setShowErrors(true);
                return;
              }
              if (!isLast) setStep((current) => current + 1);
            }}
          >
            next
          </button>
        )}
      />
    </>
  );
}

/** Each case needs its own root: re-rendering into one keeps the previous state. */
function mount(
  props: {
    serverErrors?: Record<string, string>;
    initial?: Answers;
    mode?: "public" | "admin";
  } = {},
) {
  container = testWindow.document.createElement("div");
  testWindow.document.body.appendChild(container);
  root = createRoot(container as unknown as Element);
  act(() => root.render(<Harness {...props} />));
}

function click(selector: string, index = 0) {
  const el = container.querySelectorAll(selector)[index] as unknown as HTMLElement | undefined;
  if (!el) throw new Error(`no element for ${selector}[${index}]`);
  act(() => {
    el.dispatchEvent(new testWindow.MouseEvent("click", { bubbles: true }) as unknown as Event);
  });
}

describe("SchemaForm", () => {
  it("does not offer a section whose only field is hidden", () => {
    expect(schemaSteps(SCHEMA, {}).map((section) => section.key)).toEqual(["main"]);

    mount();
    // One step means no indicator at all, so the second section's title is
    // nowhere on the surface.
    expect(container.textContent).not.toContain("Extra section");
  });

  it("reveals the gated section as soon as its controller is truthy", () => {
    expect(schemaSteps(SCHEMA, { reveal: true }).map((section) => section.key)).toEqual([
      "main",
      "extra",
    ]);

    mount();
    click('[role="switch"]');

    expect(container.textContent).toContain("Extra section");
    expect(container.querySelector('[role="switch"]')?.getAttribute("aria-checked")).toBe("true");
  });

  it("renders a server rejection under its own control", () => {
    mount({ serverErrors: { vk: "bad" } });

    const control = container.querySelector('input[aria-invalid="true"]');
    expect(control).not.toBeNull();
    const describedBy = control?.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(container.querySelector(`#${describedBy}`)?.textContent).toBe("bad");
  });

  it("blocks Next on a required field, but only complains once asked to advance", () => {
    mount();

    // Nothing is red on an untouched form: the step used to open with a
    // "required" message and a dead Next button. (The label's own "Required"
    // badge is `common.required` — a marker, not a complaint.)
    expect(container.querySelector('[aria-invalid="true"]')).toBeNull();
    expect(container.querySelector("p.text-destructive")).toBeNull();

    click("[data-next]");

    const control = container.querySelector('input[aria-invalid="true"]');
    expect(control).not.toBeNull();
    const describedBy = control?.getAttribute("aria-describedby");
    expect(container.querySelector(`#${describedBy}`)?.textContent).toBe("required");
    // Still on the first step: the gated second section was never a step, and a
    // blocked advance must not move anyway.
    expect(container.querySelector('[role="switch"]')).not.toBeNull();
  });

  it("lets an organizer past a blank required field", () => {
    // `required` is a rule for the REGISTRANT. The server runs the organizer
    // write paths with `enforce_required=False`, and the deleted
    // `UnifiedRegistrationForm` guarded the same thing: an organizer editing a
    // row that predates the question must not be locked out of unrelated fixes.
    mount({ mode: "admin", initial: { reveal: true } });
    expect(reachedStep()).toBe(0);

    click("[data-next]");

    expect(reachedStep()).toBe(1);
    expect(container.querySelector('[aria-invalid="true"]')).toBeNull();
  });

  it("still blocks an organizer on a malformed answer", () => {
    // Only `required` is waived. A value that breaks the field's own rules is
    // wrong whoever typed it — here a `select` answer outside its options.
    mount({ mode: "admin", initial: { reveal: true, vk: "x", pick: "XL" } });

    click("[data-next]");

    expect(reachedStep()).toBe(0);
    const control = container.querySelector('[aria-invalid="true"]');
    expect(control).not.toBeNull();
    const describedBy = control?.getAttribute("aria-describedby");
    expect(container.querySelector(`#${describedBy}`)?.textContent).toBe("invalid_option");
  });
});

afterAll(() => {
  act(() => root.unmount());
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});
