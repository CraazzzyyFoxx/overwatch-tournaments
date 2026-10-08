import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { PageHero } from "./PageHero";

describe("PageHero cover banner", () => {
  it("renders the banner as a blurred wash, not as a picture", () => {
    const markup = renderToStaticMarkup(
      <PageHero title="Overwatch Cup" coverUrl="https://cdn.example.test/cover.png" />
    );

    expect(markup).toContain('src="https://cdn.example.test/cover.png"');
    expect(markup).toContain('loading="lazy"');
    // Decorative only: the hero title already names the page.
    expect(markup).toContain('alt=""');
    // Blurred, oversaturated and blended, all inline: `mix-blend-mode: color`
    // takes hue from the image and luminance from the frame, so no upload can
    // move a contrast ratio, and saturation is the one channel such a blend can
    // spend. A scrim could not do this — `--aqt-fg-faint` sits at 5.1:1 on
    // `--aqt-bg`, and a white cover bleeding 5% of its light drops it to ~2.6:1.
    expect(markup).toContain("mix-blend-mode:color");
    expect(markup).toContain("blur(28px) saturate(2.2)");
    // Bled past the frame, or the blur pulls transparency in from outside the
    // image's box and the tint fades out at the top and bottom edges.
    expect(markup).toContain("inset:-96px");
    // The blend has to stay inside the hero, not reach the page behind it.
    expect(markup).toContain("isolate");
    // No band is reserved and no scrim is painted: the wash is behind the copy.
    expect(markup).not.toContain("padding-top");
  });

  it("emits no image layer without a cover, leaving the frame untouched", () => {
    const markup = renderToStaticMarkup(<PageHero title="Overwatch Cup" />);

    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("mix-blend-mode");
  });

  it("paints a right-edge bleed instead of a colour wash when asked", () => {
    const markup = renderToStaticMarkup(
      <PageHero
        title="Overwatch Cup"
        coverUrl="https://cdn.example.test/cover.png"
        coverFade="right"
      />
    );

    expect(markup).toContain('src="https://cdn.example.test/cover.png"');
    expect(markup).toContain("linear-gradient(90deg, transparent 0%, #000 55%)");
    expect(markup).not.toContain("mix-blend-mode");
    expect(markup).not.toContain("blur(28px)");
  });
});


describe("PageHero flush aside", () => {
  it("pads the copy column, not the media column", () => {
    const markup = renderToStaticMarkup(
      <PageHero title="Overwatch Cup" asideFlush aside={<img src="/poster.png" alt="" />} />
    );

    expect(markup).toContain("lg:items-stretch");
    expect(markup).toContain("minmax(0,20rem)");
    expect(markup).toContain("max-lg:hidden");
    expect(markup).not.toContain("lg:grid-cols-[1.5fr_1fr]");
  });
});
