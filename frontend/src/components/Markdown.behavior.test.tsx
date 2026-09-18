// @vitest-environment happy-dom
//
// The renderer for organizer-authored documents (tournament rules). What is
// pinned here is the security boundary plus the one plugin the feature promises:
//  1. raw HTML in the source is TEXT, never markup — an author cannot inject a
//     script, an iframe or an event handler into a public page;
//  2. a `javascript:` destination does not survive as a navigable href
//     (react-markdown's default `urlTransform`), and real links keep
//     `rel="noreferrer noopener"` since every destination is third-party;
//  3. GFM is actually wired: a pipe table renders as a table, which is how
//     tiebreakers get written.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Markdown } from "@/components/Markdown";

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

function render(source: string) {
  act(() => root.render(<Markdown source={source} />));
  return container;
}

describe("Markdown", () => {
  it("renders raw HTML as text instead of markup", () => {
    const html = render(
      '<script>window.pwned = true</script>\n\n<img src="x" onerror="window.pwned = true">'
    );

    expect(html.querySelector("script")).toBeNull();
    // The `<img>` came from the SOURCE as HTML, so it must not have become an
    // element either — the only images this renderer creates are Markdown ones.
    expect(html.querySelector("img")).toBeNull();
    expect(html.textContent).toContain("<script>");
  });

  it("neutralises a javascript: destination and hardens real links", () => {
    const html = render("[click](javascript:alert(1)) and [docs](https://example.com/rules)");

    const [unsafe, safe] = Array.from(html.querySelectorAll("a"));
    expect(unsafe.getAttribute("href")).toBe("");
    expect(safe.getAttribute("href")).toBe("https://example.com/rules");
    expect(safe.getAttribute("rel")).toBe("noreferrer noopener");
    expect(safe.getAttribute("target")).toBe("_blank");
  });

  it("renders a GFM table, scrollable, with its header cells", () => {
    const html = render(
      ["| Criterion | Order |", "| --- | --- |", "| Head-to-head | 1 |"].join("\n")
    );

    expect(html.querySelectorAll("th")).toHaveLength(2);
    expect(html.querySelector("td")?.textContent).toBe("Head-to-head");
    // A wide table must scroll inside its own box rather than stretch the page.
    expect(html.querySelector("table")?.parentElement?.className).toContain("overflow-x-auto");
  });

  it("starts the document's heading levels below the page's own h1", () => {
    const html = render("# Format\n\n## Tiebreakers");

    expect(html.querySelector("h1")).toBeNull();
    expect(html.querySelector("h2")?.textContent).toBe("Format");
    expect(html.querySelector("h3")?.textContent).toBe("Tiebreakers");
  });
});
