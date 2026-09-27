import { afterAll, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import {
  act,
  cloneElement,
  createContext,
  useContext,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import type { Hero } from "@/types/hero.types";
import type { RolesParams } from "@/types/forms.types";
import type { SubroleCatalog } from "@/types/registration.types";

import {
  createRoleSelections,
  fromRoleSelections,
  isFlexSelection,
  priorityChoice,
  toRoleSelections,
  type FlexMode,
  type RoleSelections,
} from "./types";

const testWindow = new Window({ url: "http://localhost:3000/", width: 720, height: 900 });
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
}));
vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element -- test stand-in, never shipped
  default: ({ alt }: { alt: string }) => <img alt={alt} />,
}));
// Radix portals and pointer measurement do not work under happy-dom, so the
// popover is stood in by an open/closed switch driven through the trigger. The
// closed state is what the control-set assertions measure — the roster only
// lands on the surface once its own trigger is clicked.
const PopoverCtx = createContext<{ open: boolean; setOpen: (open: boolean) => void }>({
  open: false,
  setOpen: () => {},
});
vi.mock("@/components/ui/popover", () => ({
  Popover: ({
    children,
    open = false,
    onOpenChange = () => {},
  }: {
    children: ReactNode;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }) => (
    <PopoverCtx.Provider value={{ open, setOpen: onOpenChange }}>
      <div>{children}</div>
    </PopoverCtx.Provider>
  ),
  PopoverTrigger: ({ children }: { children: ReactElement }) => {
    const { open, setOpen } = useContext(PopoverCtx);
    return cloneElement(children, { onClick: () => setOpen(!open) });
  },
  PopoverContent: ({ children }: { children: ReactNode }) =>
    useContext(PopoverCtx).open ? <div>{children}</div> : null,
}));
// Radix passes the root's `disabled` down to the trigger through context; the
// stand-in has to do the same or a disabled specialization cell looks enabled.
const SelectCtx = createContext<boolean>(false);
vi.mock("@/components/ui/select", () => ({
  Select: ({ children, disabled = false }: { children: ReactNode; disabled?: boolean }) => (
    <SelectCtx.Provider value={disabled}>
      <div>{children}</div>
    </SelectCtx.Provider>
  ),
  SelectTrigger: ({ children, ...rest }: { children: ReactNode }) => (
    <button type="button" disabled={useContext(SelectCtx)} {...rest}>
      {children}
    </button>
  ),
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
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
const RoleStep = (await import("./RoleStep")).default;

const HEROES: Hero[] = [
  ["reinhardt", "tank"],
  ["dva", "tank"],
  ["genji", "damage"],
  ["ashe", "damage"],
  ["ana", "support"],
  ["kiriko", "support"],
].map(([slug, role], index) => ({
  id: index + 1,
  slug,
  name: slug,
  role,
  type: role,
  image_path: `/heroes/${slug}.png`,
}) as unknown as Hero);

const CATALOG: SubroleCatalog = {
  tank: [{ slug: "main-tank", label: "Main tank" }],
  damage: [{ slug: "hitscan", label: "Hitscan" }],
  support: [{ slug: "main-heal", label: "Main heal" }],
};

/** `subroles: {}` offers the whole catalog, which is what these cases assume. */
function paramsFor(flexMode: FlexMode): RolesParams {
  return {
    primary_required: true,
    additional_required: false,
    flex_allowed: flexMode !== "off",
    flex_mode: flexMode === "off" ? "optional" : flexMode,
    subroles: {},
    top_heroes: { enabled: true, required: false, max: 5 },
  };
}

let container = testWindow.document.createElement("div");
let root = createRoot(container as unknown as Element);
let latest: RoleSelections = createRoleSelections();

function Harness({
  flexMode = "optional" as FlexMode,
  initial,
}: {
  flexMode?: FlexMode;
  initial?: RoleSelections;
}) {
  const [selections, setSelections] = useState<RoleSelections>(
    initial ?? createRoleSelections(flexMode),
  );
  // The matrix speaks `RoleSelections`; the stored answer is `RoleInput[]`.
  // Converting at the boundary keeps these cases written in the vocabulary
  // they assert in, and exercises the round trip on every interaction.
  return (
    <RoleStep
      params={paramsFor(flexMode)}
      subroleCatalog={CATALOG}
      value={fromRoleSelections(selections)}
      onChange={(next) => {
        const restored = toRoleSelections(next);
        latest = restored;
        setSelections(restored);
      }}
      allHeroes={HEROES}
    />
  );
}

/** Each case needs its own root: re-rendering into one keeps the previous state. */
function mount(flexMode: FlexMode = "optional", initial?: RoleSelections) {
  container = testWindow.document.createElement("div");
  testWindow.document.body.appendChild(container);
  root = createRoot(container as unknown as Element);
  latest = initial ?? createRoleSelections(flexMode);
  act(() => root.render(<Harness flexMode={flexMode} initial={initial} />));
}

function surface() {
  return {
    controls: container.querySelectorAll('button, [tabindex="0"]').length,
    elements: container.querySelectorAll("*").length,
    radios: container.querySelectorAll('[role="radio"]').length,
    stateful: container.querySelectorAll("[aria-checked],[aria-pressed]").length,
  };
}

function click(selector: string, index = 0) {
  const el = container.querySelectorAll(selector)[index] as unknown as HTMLElement | undefined;
  if (!el) throw new Error(`no element for ${selector}[${index}]`);
  act(() => {
    el.dispatchEvent(new testWindow.MouseEvent("click", { bubbles: true }) as unknown as Event);
  });
}

/** Row order is tank, damage, support — one hero-picker trigger each. */
const HERO_TRIGGER = 'button[aria-label="registration.roles.matrix.heroesLabel"]';

/** Slugs the open roster of `row` offers; the tiles carry the hero name. */
function roster(row: number) {
  click(HERO_TRIGGER, row);
  const titles = Array.from(container.querySelectorAll("button[title]")).map((tile) =>
    (tile as unknown as HTMLElement).getAttribute("title"),
  );
  click(HERO_TRIGGER, row);
  return titles;
}

/** `[role="radio"]` order is tank(off,fallback,main), damage(...), support(...). */
const MAIN = { tank: 2, damage: 5, support: 8 } as const;

describe("RoleStep", () => {
  it("keeps the rendered control set identical no matter what is selected", () => {
    mount();
    const initial = surface();
    // 3 rows x (3 priority radios + specialization + hero picker) + flex preset.
    // The roster lives behind the hero popover, so it never lands on this surface.
    expect(initial.controls).toBe(16);

    click('[role="radio"]', MAIN.damage);
    expect(surface()).toEqual(initial);

    click('[role="radio"]', MAIN.tank - 1); // tank → fallback
    expect(surface()).toEqual(initial);

    click('[aria-pressed]', 0); // flex preset
    expect(surface()).toEqual(initial);

    // Every control exposes its own state instead of relying on border colour:
    // three radiogroups of three, plus the flex preset toggle.
    expect(initial.radios).toBe(9);
    expect(initial.stateful).toBe(10);
  });

  it("allows exactly one main role, or every role for flex", () => {
    mount();

    click('[role="radio"]', MAIN.damage);
    expect(latest.damage.priority).toBe("main");

    click('[role="radio"]', MAIN.tank);
    expect(latest.tank.priority).toBe("main");
    expect(latest.damage.priority).toBe("fallback");
    expect(isFlexSelection(latest)).toBe(false);
  });

  it("marks every role main through the flex preset and keeps one main on exit", () => {
    mount();

    click('[aria-pressed]', 0);
    expect(isFlexSelection(latest)).toBe(true);

    click('[aria-pressed]', 0);
    expect(isFlexSelection(latest)).toBe(false);
    expect(Object.values(latest).filter((entry) => entry.priority === "main")).toHaveLength(1);
  });
});

describe("RoleStep flex hero roster", () => {
  it("offers only the row's own heroes, flex or not", () => {
    // Flex used to widen every row to the full roster, a leftover from the
    // layout where flex had ONE hero block instead of one per role. Picks are
    // submitted under the row's role, so Ana as a tank pick is a 422 the moment
    // the submission stops being flex.
    mount();
    click('[role="radio"]', MAIN.tank - 1); // tank → fallback; a skipped row is locked
    expect(roster(0)).toEqual(["reinhardt", "dva"]);

    click("[aria-pressed]", 0); // flex preset — every role main
    expect(isFlexSelection(latest)).toBe(true);

    expect(roster(0)).toEqual(["reinhardt", "dva"]);
    expect(roster(1)).toEqual(["genji", "ashe"]);
    expect(roster(2)).toEqual(["ana", "kiriko"]);
  });

  it("locks the specialization and hero cells of a skipped role", () => {
    // "Skip" means the role is not part of the submission, so a specialization
    // or a hero pick on it is an answer to a question that was not asked.
    mount(); // optional mode starts every role skipped
    // 3 specialization triggers + 3 hero pickers, all locked while every role
    // is skipped.
    expect(container.querySelectorAll("button[disabled]").length).toBe(6);

    click('[role="radio"]', MAIN.damage);
    expect(container.querySelectorAll("button[disabled]").length).toBe(4);

    click('[role="radio"]', MAIN.damage - 2); // damage → off again
    expect(container.querySelectorAll("button[disabled]").length).toBe(6);
  });

  it("keeps the all-roles flex choice when a top hero is picked", () => {
    // `setHeroes` normalizes, and normalization used to keep three mains only in
    // the optional mode — so one hero pick silently demoted two roles and made
    // the touched one the priority role the registrant never chose.
    mount("all_roles");
    click('[role="radio"]', 3); // flex
    expect(priorityChoice(latest)).toBe("flex");

    click(HERO_TRIGGER, 0);
    click("button[title]", 0);

    expect(latest.tank.topHeroes).toEqual(["reinhardt"]);
    expect(priorityChoice(latest)).toBe("flex");
    expect(isFlexSelection(latest)).toBe(true);
  });

  it("elects no main when a role is demoted out of the flex preset", () => {
    // Two mains is not a state the form can submit, but picking the survivor for
    // the registrant is worse: it assigns a main role nobody chose.
    mount();
    click("[aria-pressed]", 0);
    click('[role="radio"]', MAIN.tank - 1); // tank → fallback

    expect(latest.tank.priority).toBe("fallback");
    expect(Object.values(latest).filter((entry) => entry.priority === "main")).toHaveLength(0);
  });

  it("keeps a stale cross-class pick in the roster so it can be removed", () => {
    // An existing flex registration may carry one: the backend accepted it while
    // the submission was flex. Filtering it out of the roster would leave it
    // selected and unreachable, and the next non-flex submit would 422 on it.
    const loaded = createRoleSelections("optional");
    loaded.tank = { ...loaded.tank, priority: "main", topHeroes: ["ana"] };
    mount("optional", loaded);

    expect(roster(0)).toEqual(["reinhardt", "dva", "ana"]);

    click(HERO_TRIGGER, 0);
    click('button[title="ana"]');

    expect(latest.tank.topHeroes).toEqual([]);
  });
});

describe("RoleStep forced-flex mode", () => {
  it("renders no priority control and no flex preset", () => {
    mount("forced");

    // The priority radiogroups and the preset toggle are what disappear; the
    // specialization select and the hero picker stay, one per role.
    expect(surface().radios).toBe(0);
    expect(container.querySelectorAll("[aria-pressed]").length).toBe(0);
    expect(surface().controls).toBe(6);
  });

  it("starts with every role main, so the submission is flex", () => {
    mount("forced");

    expect(isFlexSelection(latest)).toBe(true);
    expect(Object.values(latest).every((entry) => entry.priority === "main")).toBe(true);
  });

  it("has no control that can take a role out of the selection", () => {
    // `off` is what would break a forced submission: buildRolesPayload only
    // sends roles whose priority is not `off`. The priority radiogroup is the
    // only control that can set it, and it is not rendered here — the
    // specialization and hero controls only ever promote. Asserted structurally
    // because the Radix Select opens a portal that happy-dom cannot drive.
    mount("forced");

    expect(container.querySelectorAll('[role="radiogroup"]').length).toBe(0);
    expect(container.querySelectorAll('[role="radio"]').length).toBe(0);
    expect(Object.values(latest).some((entry) => entry.priority === "off")).toBe(false);
  });

  it("still offers the preset in optional mode", () => {
    mount("optional");

    expect(container.querySelectorAll("[aria-pressed]").length).toBe(1);
  });

  it("offers neither the preset nor an all-main state when flex is banned", () => {
    mount("off");

    expect(container.querySelectorAll("[aria-pressed]").length).toBe(0);
    expect(surface().radios).toBe(9);
  });
});

describe("RoleStep all-roles mode", () => {
  it("replaces the three per-row priority groups with one", () => {
    mount("all_roles");

    // Four options — three roles plus flex — in a single group, against nine
    // radios across three groups in optional mode.
    expect(container.querySelectorAll('[role="radiogroup"]').length).toBe(1);
    expect(surface().radios).toBe(4);
    expect(container.querySelectorAll("[aria-pressed]").length).toBe(0);
  });

  it("starts with every role submittable but no priority chosen", () => {
    // The whole point of the mode: the role SET is not a question, the priority
    // is. `off` would drop the role from buildRolesPayload entirely.
    mount("all_roles");

    expect(Object.values(latest).some((entry) => entry.priority === "off")).toBe(false);
    expect(priorityChoice(latest)).toBeNull();
    expect(container.querySelectorAll('[aria-checked="true"]').length).toBe(0);
  });

  it("stays reachable by keyboard while nothing is chosen", () => {
    // With no checked radio every tabIndex would be -1 and the only control of
    // the mode would fall out of the tab order.
    mount("all_roles");

    expect(container.querySelectorAll('[role="radio"][tabindex="0"]').length).toBe(1);
  });

  it("picking a role leaves the other two playable, not off", () => {
    mount("all_roles");
    click('[role="radio"]', 1);

    expect(latest.damage.priority).toBe("main");
    expect(latest.tank.priority).toBe("fallback");
    expect(latest.support.priority).toBe("fallback");
    expect(priorityChoice(latest)).toBe("damage");
  });

  it("picking flex promotes all three, which is the flex submission", () => {
    mount("all_roles");
    click('[role="radio"]', 3);

    expect(isFlexSelection(latest)).toBe(true);
    expect(priorityChoice(latest)).toBe("flex");
  });

  it("switching the choice never accumulates two priority roles", () => {
    // The backend rejects anything between one primary and all three, so the
    // control has to be exclusive rather than additive.
    mount("all_roles");
    click('[role="radio"]', 0);
    click('[role="radio"]', 2);

    expect(priorityChoice(latest)).toBe("support");
    expect(Object.values(latest).filter((entry) => entry.priority === "main").length).toBe(1);
  });
});

afterAll(() => {
  act(() => root.unmount());
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});
