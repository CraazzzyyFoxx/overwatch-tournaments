// The state card's title is a heading, so a reader navigating by headings lands
// on "Not found" / "No stages yet" instead of skipping the only content there is.
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";

import { PageStateCard } from "./page-state-card";

function render(node: React.ReactNode) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={en}>
      {node}
    </NextIntlClientProvider>
  );
}

describe("PageStateCard", () => {
  it("titles a section-level state with an h2", () => {
    const html = render(<PageStateCard state="error" />);

    expect(html).toMatch(new RegExp(`<h2[^>]*>${en.common.pageState.error.title}</h2>`));
    expect(html).not.toContain("<h1");
  });

  it("titles a card that stands in for the whole page with an h1", () => {
    const html = render(<PageStateCard state="not-found" headingLevel={1} title="No access" />);

    expect(html).toContain(">No access</h1>");
    expect(html).not.toContain("<h2");
  });

  it("keeps the public empty copy for the default title only", () => {
    expect(render(<PageStateCard state="empty" />)).toContain(
      en.common.pageState.empty.description
    );

    const own = render(<PageStateCard state="empty" title="Select a workspace" />);
    expect(own).toContain("Select a workspace");
    expect(own).not.toContain(en.common.pageState.empty.description);
  });
});
