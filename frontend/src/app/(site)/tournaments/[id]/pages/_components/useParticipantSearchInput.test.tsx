import { afterAll, afterEach, beforeAll, describe, expect, it, jest } from "bun:test";
import { Window } from "happy-dom";
import { act } from "react";

import { useParticipantSearchInput } from "./useParticipantSearchInput";

const testWindow = new Window({
  url: "http://localhost:3000/tournaments/72/participants",
  width: 1280,
  height: 900
});

const globals = globalThis as typeof globalThis & Record<string, unknown>;
const previousGlobals = new Map<string, unknown>();
for (const [key, value] of Object.entries({
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
})) {
  previousGlobals.set(key, globals[key]);
  globals[key] = value;
}

const { createRoot } = await import("react-dom/client");

interface HarnessProps {
  canonicalSearch: string;
  canonicalUrl: string;
  onCommit: (value: string) => void;
}

function SearchHarness({ canonicalSearch, canonicalUrl, onCommit }: HarnessProps) {
  const { inputRef, onChange } = useParticipantSearchInput({
    canonicalSearch,
    canonicalUrl,
    onCommit,
    delay: 250
  });

  return (
    <input defaultValue={canonicalSearch} maxLength={120} onChange={onChange} ref={inputRef} />
  );
}

function dispatchInput(input: HTMLInputElement, value: string, caret = value.length) {
  const valueSetter = Object.getOwnPropertyDescriptor(
    testWindow.HTMLInputElement.prototype,
    "value"
  )?.set;
  valueSetter?.call(input, value);
  input.setSelectionRange(caret, caret);
  input.dispatchEvent(new testWindow.InputEvent("input", { bubbles: true, data: value }));
}

beforeAll(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  document.body.replaceChildren();
  jest.clearAllTimers();
});

afterAll(async () => {
  jest.useRealTimers();
  await testWindow.close();
  for (const [key, value] of previousGlobals) {
    if (value === undefined) delete globals[key];
    else globals[key] = value;
  }
});

describe("participant search URL input", () => {
  it("cancels stale debounce on Back/Forward and permits later typing", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <SearchHarness
          canonicalSearch="first"
          canonicalUrl="participantSearch=first"
          onCommit={(value) => commits.push(value)}
        />
      );
    });
    const input = container.querySelector("input")!;
    input.focus();
    act(() => dispatchInput(input, "pending"));

    act(() => {
      root.render(
        <SearchHarness
          canonicalSearch="restored"
          canonicalUrl="participantSearch=restored"
          onCommit={(value) => commits.push(value)}
        />
      );
    });
    act(() => jest.advanceTimersByTime(250));

    expect(commits).toEqual([]);
    expect(input.value).toBe("restored");
    expect(document.activeElement).toBe(input);

    act(() => dispatchInput(input, "later"));
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual(["later"]);

    act(() => dispatchInput(input, "unmounted"));
    act(() => root.unmount());
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual(["later"]);
  });

  it("strips controls, caps raw input, and displays the canonical URL value", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <SearchHarness
          canonicalSearch=""
          canonicalUrl=""
          onCommit={(value) => commits.push(value)}
        />
      );
    });
    const input = container.querySelector("input")!;
    input.focus();

    act(() => dispatchInput(input, ` foo \u0000\u0085${"x".repeat(160)} `));
    expect(input.maxLength).toBe(120);
    expect(input.value).not.toMatch(/[\u0000-\u001f\u007f-\u009f]/);
    expect(input.value).toHaveLength(120);
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual([input.value]);

    act(() => {
      root.render(
        <SearchHarness
          canonicalSearch="foo"
          canonicalUrl="participantSearch=foo"
          onCommit={(value) => commits.push(value)}
        />
      );
    });
    expect(input.value).toBe("foo");
    expect(document.activeElement).toBe(input);

    act(() => root.unmount());
  });
});
