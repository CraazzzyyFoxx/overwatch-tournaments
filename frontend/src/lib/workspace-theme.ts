/**
 * Workspace site branding — derive a full CSS-variable override set from the 4
 * organiser-controlled brand colours.
 *
 * Single source of truth for both the SSR seed (in the `(site)` layout) and the
 * client-side {@link WorkspaceThemeSync}. Pure + deterministic so it is trivially
 * unit-testable.
 *
 * FORMAT FOOTGUN — two different value formats live in this map:
 *   - `--aqt-*` tokens hold a COMPLETE colour, e.g. `hsl(174 72% 46%)`
 *     (consumed as `var(--aqt-teal)`).
 *   - shadcn tokens (`--primary`, `--background`, …) hold a BARE HSL triplet,
 *     e.g. `174 72% 46%` (consumed as `hsl(var(--primary))`).
 *
 * The app is dark-only, so background/surface are clamped into a dark lightness
 * band to keep the (light) foreground readable; accents are clamped into a
 * usable band and their on-accent foreground is contrast-picked (WCAG).
 *
 * OW role colours (`--aqt-tank/-damage/-support`), status hues
 * (`--aqt-emerald/-amber/-gold`) and chart colours carry meaning and are never
 * overridden. Beyond the 4 seed colours, organisers may override a curated core
 * set (accent/foreground/muted/border/ring/destructive); an unset override
 * simply falls back to the derived value.
 */
import type { Workspace, WorkspaceBranding } from "@/types/workspace.types";

export type CssVarMap = Record<string, string>;

interface Hsl {
  h: number;
  s: number;
  l: number;
}

interface Rgb {
  r: number;
  g: number;
  b: number;
}

// Dark-only invariant: keep page/surface dark so the light foreground stays legible.
const DARK_BG = { min: 4, max: 14 } as const;
const DARK_SURFACE = { min: 6, max: 16 } as const;
// Keep accents vivid + legible on a dark canvas without fully discarding the pick.
const ACCENT_L = { min: 40, max: 70 } as const;
const ACCENT_S_MIN = 30;

// Every CSS variable this module may set. Exported so the client sync can clear
// the whole set when switching to an unbranded workspace. Kept in lockstep with
// the map built below (a unit test asserts they match).
export const WORKSPACE_THEME_VAR_NAMES: readonly string[] = [
  // --aqt-* (full hsl(...))
  "--aqt-bg",
  "--aqt-bg-2",
  "--aqt-card",
  "--aqt-card-2",
  "--aqt-border",
  "--aqt-border-2",
  "--aqt-border-3",
  "--aqt-fg",
  "--aqt-fg-muted",
  "--aqt-fg-dim",
  "--aqt-fg-faint",
  "--aqt-teal",
  "--aqt-violet",
  // shadcn (bare "H S% L%")
  "--background",
  "--foreground",
  "--card",
  "--card-foreground",
  "--popover",
  "--popover-foreground",
  "--primary",
  "--primary-foreground",
  "--secondary",
  "--secondary-foreground",
  "--muted",
  "--muted-foreground",
  "--accent",
  "--accent-foreground",
  "--border",
  "--input",
  "--ring",
  "--destructive",
  "--destructive-foreground",
];

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

/** Parse `#RRGGBB` (or `#rgb`) → rgb, or null if malformed. */
export function parseHex(hex: string | null | undefined): Rgb | null {
  if (!hex) return null;
  let value = hex.trim().replace(/^#/, "");
  if (value.length === 3) {
    value = value
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(value)) return null;
  return {
    r: parseInt(value.slice(0, 2), 16),
    g: parseInt(value.slice(2, 4), 16),
    b: parseInt(value.slice(4, 6), 16),
  };
}

export function rgbToHsl({ r, g, b }: Rgb): Hsl {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const delta = max - min;
  const l = (max + min) / 2;

  let h = 0;
  let s = 0;
  if (delta !== 0) {
    s = l > 0.5 ? delta / (2 - max - min) : delta / (max + min);
    switch (max) {
      case rn:
        h = (gn - bn) / delta + (gn < bn ? 6 : 0);
        break;
      case gn:
        h = (bn - rn) / delta + 2;
        break;
      default:
        h = (rn - gn) / delta + 4;
        break;
    }
    h *= 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

function hue2rgb(p: number, q: number, t: number): number {
  let tt = t;
  if (tt < 0) tt += 1;
  if (tt > 1) tt -= 1;
  if (tt < 1 / 6) return p + (q - p) * 6 * tt;
  if (tt < 1 / 2) return q;
  if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
  return p;
}

export function hslToRgb({ h, s, l }: Hsl): Rgb {
  const hn = ((h % 360) + 360) % 360 / 360;
  const sn = clamp(s, 0, 100) / 100;
  const ln = clamp(l, 0, 100) / 100;
  if (sn === 0) {
    const v = Math.round(ln * 255);
    return { r: v, g: v, b: v };
  }
  const q = ln < 0.5 ? ln * (1 + sn) : ln + sn - ln * sn;
  const p = 2 * ln - q;
  return {
    r: Math.round(hue2rgb(p, q, hn + 1 / 3) * 255),
    g: Math.round(hue2rgb(p, q, hn) * 255),
    b: Math.round(hue2rgb(p, q, hn - 1 / 3) * 255),
  };
}

/** WCAG relative luminance of an sRGB colour. */
function relLuminance({ r, g, b }: Rgb): number {
  const lin = [r, g, b].map((c) => {
    const cs = c / 255;
    return cs <= 0.03928 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

const FG_LIGHT = "0 0% 98%";
const FG_DARK = "0 0% 9%";

/** Pick black/white foreground for text sitting on `bg`, by WCAG contrast. */
function pickOnColorForeground(bg: Rgb): string {
  const lum = relLuminance(bg);
  const contrastWhite = 1.05 / (lum + 0.05);
  const contrastBlack = (lum + 0.05) / 0.05;
  return contrastBlack > contrastWhite ? FG_DARK : FG_LIGHT;
}

const round = (n: number): number => Math.round(n);

/** `--aqt-*` value: a complete `hsl(...)`. */
function fullHsl({ h, s, l }: Hsl): string {
  return `hsl(${round(((h % 360) + 360) % 360)} ${round(clamp(s, 0, 100))}% ${round(clamp(l, 0, 100))}%)`;
}

/** shadcn value: a bare `H S% L%` triplet. */
function triplet({ h, s, l }: Hsl): string {
  return `${round(((h % 360) + 360) % 360)} ${round(clamp(s, 0, 100))}% ${round(clamp(l, 0, 100))}%`;
}

function clampBackground(hsl: Hsl, band: { min: number; max: number }): Hsl {
  return { h: hsl.h, s: clamp(hsl.s, 0, 45), l: clamp(hsl.l, band.min, band.max) };
}

function clampAccent(hsl: Hsl): Hsl {
  return { h: hsl.h, s: clamp(hsl.s, ACCENT_S_MIN, 95), l: clamp(hsl.l, ACCENT_L.min, ACCENT_L.max) };
}

/**
 * Build the CSS-variable override map from workspace branding, or `null` when
 * branding is disabled / lacks the minimum colours (→ callers fall back to the
 * default palette).
 *
 * Minimum input is `brand_primary` + `brand_background`; a missing secondary
 * falls back to primary and a missing surface is derived from the background.
 */
export function deriveWorkspacePalette(
  branding: WorkspaceBranding | Workspace | null | undefined
): CssVarMap | null {
  if (!branding || !branding.branding_enabled) return null;

  const primaryRgb = parseHex(branding.brand_primary);
  const backgroundRgb = parseHex(branding.brand_background);
  if (!primaryRgb || !backgroundRgb) return null;

  const secondaryRgb = parseHex(branding.brand_secondary);
  const surfaceRgb = parseHex(branding.brand_surface);

  const bg = clampBackground(rgbToHsl(backgroundRgb), DARK_BG);
  const surface = surfaceRgb
    ? clampBackground(rgbToHsl(surfaceRgb), DARK_SURFACE)
    : { h: bg.h, s: bg.s, l: clamp(bg.l + 2, DARK_SURFACE.min, DARK_SURFACE.max) };
  const accent = clampAccent(rgbToHsl(primaryRgb));
  const secondary = secondaryRgb ? clampAccent(rgbToHsl(secondaryRgb)) : accent;

  // Light foreground, faintly tinted with the background hue for cohesion.
  const fg: Hsl = { h: bg.h, s: 16, l: 96 };
  const fgMuted: Hsl = { h: bg.h, s: 12, l: 62 };
  const fgDim: Hsl = { h: bg.h, s: 12, l: 42 };
  const fgFaint: Hsl = { h: bg.h, s: 12, l: 32 };

  // Borders step up in lightness from the surface.
  const border: Hsl = { h: surface.h, s: surface.s, l: clamp(surface.l + 6, 8, 24) };
  const border2: Hsl = { h: surface.h, s: surface.s, l: clamp(surface.l + 10, 10, 28) };
  const border3: Hsl = { h: surface.h, s: surface.s, l: clamp(surface.l + 14, 12, 32) };

  const bg2: Hsl = { h: bg.h, s: bg.s, l: clamp(bg.l + 1, DARK_BG.min, DARK_BG.max + 2) };
  const card2: Hsl = { h: surface.h, s: surface.s, l: clamp(surface.l + 1, DARK_SURFACE.min, DARK_SURFACE.max + 2) };
  const mutedSurface: Hsl = { h: surface.h, s: surface.s, l: clamp(surface.l + 4, 8, 22) };

  const onAccent = pickOnColorForeground(hslToRgb(accent));
  const onSecondary = pickOnColorForeground(hslToRgb(secondary));

  // Curated core-palette overrides: a valid hex wins over the derived value.
  // Surface-like tokens (accent/muted/border) are clamped into the dark band so
  // they stay legible on the dark canvas; ring uses the accent band; foreground
  // is used near as-given; destructive defaults to the standard red when unset.
  const accentSurface = parseHex(branding.brand_accent);
  const foregroundRgb = parseHex(branding.brand_foreground);
  const mutedRgb = parseHex(branding.brand_muted);
  const borderRgb = parseHex(branding.brand_border);
  const ringRgb = parseHex(branding.brand_ring);
  const destructiveRgb = parseHex(branding.brand_destructive);

  const accentHsl = accentSurface ? clampBackground(rgbToHsl(accentSurface), { min: 6, max: 26 }) : mutedSurface;
  const fgFinal = foregroundRgb ? rgbToHsl(foregroundRgb) : fg;
  const mutedFinal = mutedRgb ? clampBackground(rgbToHsl(mutedRgb), { min: 6, max: 26 }) : mutedSurface;
  const borderFinal = borderRgb ? clampBackground(rgbToHsl(borderRgb), { min: 6, max: 34 }) : border;
  const ringFinal = ringRgb ? clampAccent(rgbToHsl(ringRgb)) : accent;
  const destructive: Hsl = destructiveRgb ? clampAccent(rgbToHsl(destructiveRgb)) : { h: 0, s: 72, l: 51 };
  const onAccentSurface = pickOnColorForeground(hslToRgb(accentHsl));
  const onDestructive = pickOnColorForeground(hslToRgb(destructive));

  return {
    // ── --aqt-* (full hsl) ──
    "--aqt-bg": fullHsl(bg),
    "--aqt-bg-2": fullHsl(bg2),
    "--aqt-card": fullHsl(surface),
    "--aqt-card-2": fullHsl(card2),
    "--aqt-border": fullHsl(borderFinal),
    "--aqt-border-2": fullHsl(border2),
    "--aqt-border-3": fullHsl(border3),
    "--aqt-fg": fullHsl(fgFinal),
    "--aqt-fg-muted": fullHsl(fgMuted),
    "--aqt-fg-dim": fullHsl(fgDim),
    "--aqt-fg-faint": fullHsl(fgFaint),
    "--aqt-teal": fullHsl(accent),
    "--aqt-violet": fullHsl(secondary),
    // ── shadcn (bare triplet) ──
    "--background": triplet(bg),
    "--foreground": triplet(fgFinal),
    "--card": triplet(surface),
    "--card-foreground": triplet(fgFinal),
    "--popover": triplet(surface),
    "--popover-foreground": triplet(fgFinal),
    "--primary": triplet(accent),
    "--primary-foreground": onAccent,
    "--secondary": triplet(secondary),
    "--secondary-foreground": onSecondary,
    "--muted": triplet(mutedFinal),
    "--muted-foreground": triplet(fgMuted),
    "--accent": triplet(accentHsl),
    "--accent-foreground": onAccentSurface,
    "--border": triplet(borderFinal),
    "--input": triplet(borderFinal),
    "--ring": triplet(ringFinal),
    "--destructive": triplet(destructive),
    "--destructive-foreground": onDestructive,
  };
}

/** Apply a derived palette (or clear it) on an element via inline CSS vars. */
export function applyWorkspacePalette(el: HTMLElement, palette: CssVarMap | null): void {
  for (const name of WORKSPACE_THEME_VAR_NAMES) {
    el.style.removeProperty(name);
  }
  if (palette) {
    for (const [name, value] of Object.entries(palette)) {
      el.style.setProperty(name, value);
    }
  }
}
