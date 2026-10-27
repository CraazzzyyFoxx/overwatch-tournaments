import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { SITE_NAME } from "@/config/site";
import { PLATFORM_ZONE } from "@/lib/site/host";

import { ACCENT, BG, FAINT, FG, MUTED, OG_SIZE, loadOgFonts } from "./base";

let markPromise: Promise<string | null> | null = null;

/** `public/brand-mark.svg`, inlined like the encounter card's crests: no round trip into our own origin. */
function loadMark() {
  markPromise ??= readFile(join(process.cwd(), "public", "brand-mark.svg"))
    .then((data) => `data:image/svg+xml;base64,${data.toString("base64")}`)
    .catch((error) => {
      console.error("opengraph-image: missing brand mark:", error);
      return null;
    });
  return markPromise;
}

/**
 * The share card of a platform landing (`/`, `/get-workspace`): the brand, the
 * page's own headline and lede, the platform's address, under the teal rule
 * every hero carries. The headline is one colour: its accent word is a
 * rich-text tag the caller flattens.
 */
export async function renderLandingOg({ title, lede }: { title: string; lede: string }) {
  const [fonts, mark] = await Promise.all([loadOgFonts(), loadMark()]);

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: BG,
        color: FG,
        fontFamily: "Onest",
        borderTop: `6px solid ${ACCENT}`,
        padding: "56px 64px"
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {mark ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mark} alt="" width={56} height={56} />
        ) : null}
        <div style={{ display: "flex", fontSize: 34, fontWeight: 700 }}>{SITE_NAME}</div>
      </div>
      <div style={{ display: "flex", flexGrow: 1 }} />
      <div style={{ display: "flex", maxWidth: 1000, fontSize: 64, fontWeight: 700, lineHeight: 1.1 }}>
        {title}
      </div>
      <div style={{ display: "flex", maxWidth: 960, marginTop: 24, fontSize: 30, lineHeight: 1.4, color: MUTED }}>
        {lede}
      </div>
      <div style={{ display: "flex", marginTop: 48, fontSize: 24, color: FAINT }}>{PLATFORM_ZONE}</div>
    </div>,
    { ...OG_SIZE, fonts }
  );
}
