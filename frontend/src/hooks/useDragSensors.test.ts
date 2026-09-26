// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useDragSensors } from "@/hooks/useDragSensors";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** The descriptors the hook would hand a `DndContext`, read back out of the DOM. */
function renderSensors(options?: Parameters<typeof useDragSensors>[0]) {
  function Probe() {
    const sensors = useDragSensors(options);
    return createElement(
      "output",
      null,
      JSON.stringify(
        sensors.map((entry) => ({ sensor: entry.sensor.name, options: entry.options }))
      )
    );
  }
  act(() => root.render(createElement(Probe)));
  return JSON.parse(container.textContent ?? "[]") as {
    sensor: string;
    options: { activationConstraint?: { distance: number } };
  }[];
}

describe("useDragSensors", () => {
  it("guards a click with a pointer threshold by default, and adds no keyboard sensor", () => {
    const sensors = renderSensors();

    expect(sensors.map((entry) => entry.sensor)).toEqual(["PointerSensor"]);
    expect(sensors[0].options).toEqual({ activationConstraint: { distance: 6 } });
  });

  it("leaves the pointer unconstrained at distance 0 -- not a zero-pixel constraint, which only starts a drag after a move", () => {
    const sensors = renderSensors({ distance: 0 });

    expect(sensors[0].options).not.toHaveProperty("activationConstraint");
  });

  it("adds the keyboard sensor on request, keeping the pointer threshold asked for", () => {
    const sensors = renderSensors({ distance: 4, keyboard: true });

    expect(sensors.map((entry) => entry.sensor)).toEqual(["PointerSensor", "KeyboardSensor"]);
    expect(sensors[0].options).toEqual({ activationConstraint: { distance: 4 } });
  });
});
