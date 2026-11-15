// @vitest-environment happy-dom
//
// A settings page between its neighbours. What is pinned here:
//  1. scrolling on past the end opens the next page, and two flicks with a
//     pause between them are not one pull;
//  2. scrolling up past the top opens the previous page;
//  3. the wheel gesture that opened a page does not coast on into the next;
//  4. while the page has unsaved edits, no amount of scrolling leaves it —
//     scrolling must never be the way to lose them;
//  5. the ghost is the next page's own render, but its groups stay out of the
//     current page's outline.
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SaveBar } from "@craazzzyyfoxx/admin-kit/kit/SaveBar";
import { SectionNav } from "@/components/kit/SectionNav";
import { SettingGroup } from "@/components/kit/SettingRow";
import { SettingsContinuation, useUnsavedReporter } from "@/components/kit/SettingsContinuation";
import { SettingsOutlineProvider } from "@/components/kit/SettingsOutline";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const push = vi.fn();
const router = { push, prefetch: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router
}));

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; scroll?: boolean; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, scroll: _scroll, ...props }, ref) {
    return (
      <a ref={ref} href={href} {...props}>
        {children}
      </a>
    );
  })
}));

const NAV = [
  {
    items: [
      { key: "domain", label: "Domain", href: "/admin/settings/domain" },
      { key: "discord", label: "Discord", href: "/admin/settings/discord" }
    ]
  }
];

let container: HTMLDivElement;
let root: Root;

async function render({ dirty = false }: { dirty?: boolean } = {}) {
  await act(async () => {
    root.render(
      <SettingsOutlineProvider>
        <SectionNav groups={NAV} activeKey="domain" />
        <SettingsContinuation
          previous={{ href: "/admin/settings/visibility", title: "Profile · Visibility" }}
          next={{
            href: "/admin/settings/discord",
            title: "Discord",
            preview: ["server", "announcements", "mixes"].map((id) => (
              <SettingGroup key={id} id={id} title={id}>
                <p>{id}</p>
              </SettingGroup>
            ))
          }}
        >
          {["address", "custom-domain", "search"].map((id) => (
            <SettingGroup key={id} id={id} title={id}>
              <p>{id}</p>
            </SettingGroup>
          ))}
          <FormBar dirty={dirty} />
        </SettingsContinuation>
      </SettingsOutlineProvider>
    );
  });
}

/** A form's save bar, wired to the continuation the way every settings form wires it. */
function FormBar({ dirty }: Readonly<{ dirty: boolean }>) {
  const reportUnsaved = useUnsavedReporter();
  return (
    <SaveBar
      dirty={dirty}
      summary="1 changed field"
      onDiscard={() => {}}
      onSave={() => {}}
      onDirtyChange={reportUnsaved}
    />
  );
}

async function wheel(deltaY: number, times: number) {
  for (let turn = 0; turn < times; turn += 1) {
    await act(async () => {
      window.dispatchEvent(new WheelEvent("wheel", { deltaY }));
    });
  }
}

/** Lets the page sit still long enough for a new wheel gesture to count. */
async function pause(ms = 300) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"]
  });
  push.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("SettingsContinuation", () => {
  it("opens the next page once the reader keeps scrolling past the end", async () => {
    await render();
    await pause();

    await wheel(100, 2);
    await pause(1000);
    await wheel(100, 2);
    expect(push).not.toHaveBeenCalled();

    await wheel(100, 2);
    expect(push).toHaveBeenCalledWith("/admin/settings/discord", { scroll: false });
  });

  it("opens the previous page once the reader keeps scrolling up past the top", async () => {
    await render();
    await pause();

    await wheel(-100, 4);

    expect(push).toHaveBeenCalledWith("/admin/settings/visibility", { scroll: false });
  });

  it("does not let the gesture that opened a page coast on into the next one", async () => {
    await render();

    await wheel(200, 10);
    expect(push).not.toHaveBeenCalled();

    await pause();
    await wheel(200, 2);
    expect(push).toHaveBeenCalledTimes(1);
  });

  it("never leaves a page with unsaved edits by scrolling", async () => {
    await render({ dirty: true });
    await pause();

    await wheel(200, 10);
    await pause(1000);
    await wheel(-200, 10);

    expect(push).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Save or discard your changes to move on");
  });

  it("keeps the next page's groups out of this page's outline", async () => {
    await render();

    const listed = [...container.querySelectorAll("nav ul ul a")].map((link) =>
      link.getAttribute("href")
    );
    expect(listed).toEqual(["#address", "#custom-domain", "#search"]);
  });
});
