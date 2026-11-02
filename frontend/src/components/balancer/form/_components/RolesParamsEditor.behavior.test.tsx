// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it } from "vitest";

import type { RoleOntology } from "@/lib/roster/ontology";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";

import {
  RolesParamsEditor,
  rolesParamsOf,
  withSingleRole,
  type SubroleCatalogByRole
} from "./RolesParamsEditor";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mount(ontology: RoleOntology | null, catalog: SubroleCatalogByRole) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <RolesParamsEditor params={rolesParamsOf({})} onChange={() => {}} catalog={catalog} ontology={ontology} />,
    );
  });
  return container.textContent ?? "";
}

/** Whether the names appear, in that order, in the rendered text. */
function inOrder(text: string, names: string[]): boolean {
  const positions = names.map((name) => text.indexOf(name));
  return positions.every((position, index) => position >= 0 && (index === 0 || position > positions[index - 1]));
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("RolesParamsEditor sub-role rows", () => {
  it("offers one row per Overwatch role", async () => {
    const text = await mount(OW_METADATA, { tank: [{ id: 1, slug: "main_tank", label: "Main Tank" }] });

    expect(inOrder(text, ["Tank", "Damage", "Support"])).toBe(true);
    expect(text).toContain("Main Tank");
    expect(text).not.toContain("Jungle");
  });

  it("offers one row per League position, with that position's sub-roles", async () => {
    const text = await mount(LOL_METADATA, { jungle: [{ id: 2, slug: "ganker", label: "Ganker" }] });

    expect(inOrder(text, ["Top", "Jungle", "Mid", "Bot", "Support"])).toBe(true);
    expect(text).toContain("Ganker");
    expect(text).not.toContain("Damage");
  });

  it("invents no role while the game's dictionary loads", async () => {
    const text = await mount(null, {});

    expect(text).not.toContain("Tank");
    expect(text).not.toContain("Jungle");
  });
});

describe("single-role switch", () => {
  it.each([
    ["all_roles", { flex_mode: "all_roles" as const }],
    ["forced", { flex_mode: "forced" as const }],
    ["additional_required", { additional_required: true }],
    ["flex allowed", { flex_allowed: true }]
  ])("switched on from %s yields a consistent one-role config", (_name, override) => {
    const next = withSingleRole({ ...rolesParamsOf({}), ...override }, true);

    expect(next).toMatchObject({
      max_roles: 1,
      flex_allowed: false,
      flex_mode: "optional",
      additional_required: false
    });
  });

  it("switched off lifts only the cap", () => {
    const on = withSingleRole(rolesParamsOf({ additional_required: true, flex_mode: "forced" }), true);

    expect(withSingleRole(on, false)).toEqual({ ...on, max_roles: null });
  });

  it("locks the conflicting controls while the cap is on", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    await act(async () => {
      createRoot(container).render(
        <RolesParamsEditor
          params={withSingleRole(rolesParamsOf({}), true)}
          onChange={() => {}}
          catalog={{}}
          ontology={OW_METADATA}
        />,
      );
    });

    const disabled = (id: string) =>
      (container.querySelector(`[id$="-${id}"]`) as HTMLButtonElement | null)?.disabled;
    expect(disabled("additional")).toBe(true);
    expect(disabled("flex")).toBe(true);
    expect(disabled("mode")).toBe(true);
    expect(disabled("primary")).toBe(false);
    expect(disabled("single")).toBe(false);
  });
});
