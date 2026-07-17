import { afterAll, afterEach, beforeAll, describe, expect, it, mock } from "bun:test";
import { Window } from "happy-dom";
import { act } from "react";
import type { createRoot as CreateRoot, Root } from "react-dom/client";

import { TimeInput } from "./time-input";

const testWindow = new Window({ url: "http://localhost:3000" });
const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();
let createRoot: typeof CreateRoot;
let root: Root | undefined;

function installGlobals() {
  const values = {
    window: testWindow,
    document: testWindow.document,
    navigator: testWindow.navigator,
    HTMLElement: testWindow.HTMLElement,
    Event: testWindow.Event,
    InputEvent: testWindow.InputEvent,
    Node: testWindow.Node,
    MutationObserver: testWindow.MutationObserver,
    getComputedStyle: testWindow.getComputedStyle.bind(testWindow),
    requestAnimationFrame: testWindow.requestAnimationFrame.bind(testWindow),
    cancelAnimationFrame: testWindow.cancelAnimationFrame.bind(testWindow),
    IS_REACT_ACT_ENVIRONMENT: true
  };

  for (const [key, value] of Object.entries(values)) {
    previousGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, value, writable: true });
  }
}

function dispatchInput(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(
    testWindow.HTMLInputElement.prototype,
    "value"
  )?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new testWindow.InputEvent("input", { bubbles: true, data: value }));
}

beforeAll(async () => {
  installGlobals();
  // React DOM must load after happy-dom globals exist in this test process.
  ({ createRoot } = await import("react-dom/client"));
});

afterEach(() => {
  act(() => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
});

afterAll(async () => {
  await testWindow.close();
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});

describe("TimeInput", () => {
  it("accepts compact time and normalizes it on blur", () => {
    const onValueChange = mock(() => undefined);
    const container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    act(() => root?.render(<TimeInput value="18:45" onValueChange={onValueChange} />));
    const input = container.querySelector("input") as HTMLInputElement;

    act(() => dispatchInput(input, "930"));
    act(() => {
      input.focus();
      input.blur();
    });

    expect(input.type).toBe("text");
    expect(input.inputMode).toBe("numeric");
    expect(input.value).toBe("09:30");
    expect(onValueChange).toHaveBeenLastCalledWith("09:30");
  });

  it("rejects an out-of-range time without changing the controlled value", () => {
    const onValueChange = mock(() => undefined);
    const container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    act(() => root?.render(<TimeInput value="18:45" onValueChange={onValueChange} />));
    const input = container.querySelector("input") as HTMLInputElement;

    act(() => dispatchInput(input, "29:00"));
    expect(input.getAttribute("aria-invalid")).toBe("true");

    act(() => {
      input.focus();
      input.blur();
    });

    expect(input.value).toBe("18:45");
    expect(onValueChange).not.toHaveBeenCalled();
  });
});
