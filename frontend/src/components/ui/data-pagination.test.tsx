import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";

import { DataPagination, buildPageWindow } from "./data-pagination";

const messages = {
  common: {
    pagination: {
      label: "Pagination",
      previous: "Previous page",
      next: "Next page",
      goToPage: "Go to page {page}"
    }
  }
};

function render(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={messages}>
      {node}
    </NextIntlClientProvider>
  );
}

// The leading wrapper is the thing that regressed: with a single page the
// component used to bypass it entirely and emit a bare `<div className={…}>`,
// so "Showing 1–2 of 2" rendered at default size and color, flush against the
// card edge, with none of the chrome the caller's className provides.
const LEADING_WRAPPER = '<div class="text-label text-[color:var(--aqt-fg-dim)]">';

describe("DataPagination", () => {
  it("styles the leading content identically whether or not page controls render", () => {
    const single = render(
      <DataPagination page={1} totalPages={1} onPageChange={() => {}} leading="Showing 1–2 of 2" />
    );
    const multiple = render(
      <DataPagination page={1} totalPages={5} onPageChange={() => {}} leading="Showing 1–2 of 2" />
    );

    expect(single).toContain(LEADING_WRAPPER);
    expect(multiple).toContain(LEADING_WRAPPER);
  });

  it("keeps the caller's chrome on the single-page shell", () => {
    const html = render(
      <DataPagination
        page={1}
        totalPages={1}
        onPageChange={() => {}}
        className="border-t px-4 py-3"
        leading="Showing 1–2 of 2"
      />
    );

    expect(html).toContain("border-t px-4 py-3");
    // Layout classes come from the shared shell, not from the caller.
    expect(html).toContain("flex flex-wrap items-center gap-3");
  });

  it("omits the navigation landmark and page buttons when there is one page", () => {
    const html = render(
      <DataPagination page={1} totalPages={1} onPageChange={() => {}} leading="Showing 1–2 of 2" />
    );

    expect(html).not.toContain("<nav");
    expect(html).not.toContain("Previous page");
  });

  it("renders nothing when there is one page and no leading content", () => {
    expect(render(<DataPagination page={1} totalPages={1} onPageChange={() => {}} />)).toBe("");
  });

  it("marks the current page and labels both arrows", () => {
    const html = render(<DataPagination page={3} totalPages={9} onPageChange={() => {}} />);

    expect(html).toContain('aria-current="page"');
    expect(html).toContain('aria-label="Previous page"');
    expect(html).toContain('aria-label="Next page"');
    expect(html).toContain('aria-label="Pagination"');
  });

  it("windows the page list around the current page", () => {
    expect(buildPageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(buildPageWindow(1, 20)).toEqual([1, 2, 3, 4, 5, null, 20]);
    expect(buildPageWindow(10, 20)).toEqual([1, null, 9, 10, 11, 12, null, 20]);
    expect(buildPageWindow(20, 20)).toEqual([1, null, 16, 17, 18, 19, 20]);
  });
});
