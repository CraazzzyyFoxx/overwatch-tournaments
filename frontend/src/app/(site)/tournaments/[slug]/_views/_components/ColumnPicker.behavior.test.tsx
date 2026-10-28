// @vitest-environment happy-dom
//
// The participants table's "Columns" menu: the mandatory identity and status
// columns stay checked and locked, any other toggles and keeps the menu open.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";

import ColumnPicker from "./ColumnPicker";
import type { ColumnDefinition } from "./participantsColumns.model";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

function column(id: string, label: string, category: ColumnDefinition["category"]): ColumnDefinition {
  return { id, label, category, defaultVisible: true, render: () => null };
}

function item(label: string): Element {
  const node = [...document.querySelectorAll("[role='menuitemcheckbox']")].find(
    (candidate) => candidate.textContent?.trim() === label
  );
  if (!node) throw new Error(`no column "${label}"`);
  return node;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = "";
});

it("locks the mandatory columns and toggles the rest without closing", async () => {
  const toggled: string[] = [];
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <ColumnPicker
          columns={[column("_identity", "Player", "built_in"), column("_status", "Status", "meta"), column("notes", "Notes", "built_in")]}
          visibility={{ _identity: true, _status: true, notes: false }}
          onToggle={(id) => toggled.push(id)}
          onReset={() => {}}
        />
      </NextIntlClientProvider>
    );
  });

  // Radix opens on `pointerdown`, so a bare click never reaches the menu.
  await act(async () => {
    container.querySelector("button")!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    await tick();
  });

  expect(item("Player").getAttribute("aria-disabled")).toBe("true");
  expect(item("Player").getAttribute("aria-checked")).toBe("true");
  expect(item("Status").getAttribute("aria-disabled")).toBe("true");
  expect(item("Notes").getAttribute("aria-checked")).toBe("false");

  for (const label of ["Player", "Status", "Notes"]) {
    await act(async () => {
      item(label).dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });
  }
  expect(toggled).toEqual(["notes"]);
  expect(item("Notes")).toBeTruthy();
});
