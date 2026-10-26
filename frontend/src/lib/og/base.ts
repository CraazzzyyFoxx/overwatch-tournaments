import { readFile } from "node:fs/promises";
import { join } from "node:path";

/** Every Open Graph card the site renders. */
export const OG_SIZE = { width: 1200, height: 630 };

/**
 * Satori rasterizes outside the browser: it cannot read `woff2`, and the font
 * bundled with `next/og` carries no Cyrillic, so half of every roster would
 * come out as tofu. These are static instances of the same vendored Onest the
 * site itself loads (see `src/app/fonts/README.md`). `next.config.mjs` traces
 * them into the standalone output, where `process.cwd()` is the app root.
 */
const FONT_DIR = join(process.cwd(), "src", "app", "fonts");

let fontsPromise: Promise<
  { name: string; data: Buffer; weight: 400 | 700; style: "normal" }[]
> | null = null;

export function loadOgFonts() {
  // Read once per process: the files never change under a running server.
  fontsPromise ??= Promise.all([
    readFile(join(FONT_DIR, "onest-400.ttf")),
    readFile(join(FONT_DIR, "onest-700.ttf"))
  ]).then(([regular, bold]) => [
    { name: "Onest", data: regular, weight: 400 as const, style: "normal" as const },
    { name: "Onest", data: bold, weight: 700 as const, style: "normal" as const }
  ]);
  return fontsPromise;
}

// Every colour below is a literal hex on purpose: Satori cannot resolve the
// `--aqt-*` custom properties, so the dark theme is mirrored by hand — the same
// trade the player card (`users/[slug]/opengraph-image.tsx`) makes.
export const BG = "linear-gradient(135deg, #0b1120 0%, #111a2e 100%)";
export const FG = "#e8eef7";
export const MUTED = "#8aa0bd";
export const FAINT = "#6b7f9c";
export const LINE = "#1f2b45";
export const ACCENT = "#2dd4bf";
