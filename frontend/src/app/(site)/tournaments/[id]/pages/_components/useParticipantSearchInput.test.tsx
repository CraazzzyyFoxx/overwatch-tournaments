import { afterAll, afterEach, beforeAll, describe, expect, it, jest } from "bun:test";
import { Window } from "happy-dom";
import { act } from "react";
import type { Root } from "react-dom/client";

import { useParticipantSearchInput } from "./useParticipantSearchInput";

const testWindow = new Window({
  url: "http://localhost:3000/tournaments/72/participants",
  width: 1280,
  height: 900
});

const previousGlobals = new Map<PropertyKey, PropertyDescriptor | undefined>();
const mountedRoots = new Set<Root>();
let createRoot: typeof import("react-dom/client").createRoot;

function restoreGlobals() {
  for (const [key, descriptor] of previousGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
  previousGlobals.clear();
}

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

  try {
    for (const [key, value] of Object.entries(values)) {
      previousGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, {
        configurable: true,
        value,
        writable: true
      });
    }
  } catch (error) {
    restoreGlobals();
    throw error;
  }
}

function createTestRoot(container: Element) {
  const root = createRoot(container);
  mountedRoots.add(root);
  return root;
}

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

beforeAll(async () => {
  installGlobals();
  ({ createRoot } = await import("react-dom/client"));
  jest.useFakeTimers();
});

afterEach(() => {
  try {
    act(() => {
      for (const root of mountedRoots) root.unmount();
    });
  } finally {
    mountedRoots.clear();
    document.body.replaceChildren();
    jest.clearAllTimers();
  }
});

afterAll(async () => {
  try {
    jest.useRealTimers();
    await testWindow.close();
  } finally {
    restoreGlobals();
  }
});

describe("participant search URL input", () => {
  it("canonicalizes surrounding whitespace after a no-op URL commit", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

    act(() => {
      root.render(
        <SearchHarness
          canonicalSearch="foo"
          canonicalUrl="participantSearch=foo"
          onCommit={(value) => commits.push(value)}
        />
      );
    });
    const input = container.querySelector("input")!;
    input.focus();

    act(() => dispatchInput(input, " foo "));
    expect(input.value).toBe(" foo ");
    act(() => jest.advanceTimersByTime(250));

    expect(commits).toEqual(["foo"]);
    expect(input.value).toBe("foo");
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(3);
    expect(input.selectionEnd).toBe(3);

  });

  it("clears whitespace-only input but leaves ordinary internal spaces typable", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

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

    act(() => dispatchInput(input, "   "));
    expect(input.value).toBe("   ");
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual([""]);
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(0);

    act(() => dispatchInput(input, "foo bar", 4));
    expect(input.value).toBe("foo bar");
    expect(input.selectionStart).toBe(4);
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual(["", "foo bar"]);
    expect(input.value).toBe("foo bar");
    expect(input.selectionStart).toBe(4);

  });

  it("maps the caret across trimmed prefixes, trailing whitespace, and the cap", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

    act(() => {
      root.render(
        <SearchHarness canonicalSearch="" canonicalUrl="" onCommit={() => {}} />
      );
    });
    const input = container.querySelector("input")!;
    input.focus();

    act(() => dispatchInput(input, "\u0000foo", 2));
    expect(input.value).toBe("foo");
    expect(input.selectionStart).toBe(1);
    act(() => jest.advanceTimersByTime(250));
    expect(input.selectionStart).toBe(1);

    act(() => dispatchInput(input, "  foo  ", 1));
    act(() => jest.advanceTimersByTime(250));
    expect(input.value).toBe("foo");
    expect(input.selectionStart).toBe(0);

    act(() => dispatchInput(input, "  foo  ", 3));
    act(() => jest.advanceTimersByTime(250));
    expect(input.value).toBe("foo");
    expect(input.selectionStart).toBe(1);

    act(() => dispatchInput(input, "foo  ", 4));
    act(() => jest.advanceTimersByTime(250));
    expect(input.value).toBe("foo");
    expect(input.selectionStart).toBe(3);

    act(() => dispatchInput(input, "x".repeat(130), 125));
    expect(input.value).toHaveLength(120);
    expect(input.selectionStart).toBe(120);
    act(() => jest.advanceTimersByTime(250));
    expect(input.value).toHaveLength(120);
    expect(input.selectionStart).toBe(120);
    expect(document.activeElement).toBe(input);

  });

  it("cancels stale debounce on Back/Forward and permits later typing", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

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
    mountedRoots.delete(root);
    act(() => jest.advanceTimersByTime(250));
    expect(commits).toEqual(["later"]);
  });

  it("strips controls, caps raw input, and displays the canonical URL value", () => {
    const commits: string[] = [];
    const container = document.createElement("div");
    document.body.append(container);
    const root = createTestRoot(container);

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

  });
});
