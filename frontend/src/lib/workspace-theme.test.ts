import { describe, expect, it } from "bun:test";

import type { WorkspaceBranding } from "@/types/workspace.types";
import {
  deriveWorkspacePalette,
  parseHex,
  rgbToHsl,
  WORKSPACE_THEME_VAR_NAMES,
} from "@/lib/workspace-theme";

const FULL: WorkspaceBranding = {
  branding_enabled: true,
  brand_primary: "#14b8a6",
  brand_secondary: "#8b5cf6",
  brand_background: "#0b1220",
  brand_surface: "#111a2b",
};

function lightnessOf(triplet: string): number {
  // "H S% L%" → L
  const match = triplet.match(/(\d+)%\s*$/);
  return match ? Number(match[1]) : NaN;
}

describe("deriveWorkspacePalette", () => {
  it("returns null when branding is disabled", () => {
    expect(deriveWorkspacePalette({ ...FULL, branding_enabled: false })).toBeNull();
  });

  it("returns null when branding is missing", () => {
    expect(deriveWorkspacePalette(null)).toBeNull();
    expect(deriveWorkspacePalette(undefined)).toBeNull();
  });

  it("returns null without the minimum colours (primary + background)", () => {
    expect(deriveWorkspacePalette({ ...FULL, brand_primary: null })).toBeNull();
    expect(deriveWorkspacePalette({ ...FULL, brand_background: null })).toBeNull();
    expect(deriveWorkspacePalette({ ...FULL, brand_primary: "not-a-color" })).toBeNull();
  });

  it("builds exactly the exported variable set (no drift, no extras)", () => {
    const palette = deriveWorkspacePalette(FULL)!;
    expect(palette).not.toBeNull();
    expect(new Set(Object.keys(palette))).toEqual(new Set(WORKSPACE_THEME_VAR_NAMES));
  });

  it("uses full hsl() for --aqt-* and bare triplets for shadcn tokens", () => {
    const palette = deriveWorkspacePalette(FULL)!;
    expect(palette["--aqt-bg"]).toMatch(/^hsl\(\d+ \d+% \d+%\)$/);
    expect(palette["--aqt-teal"]).toMatch(/^hsl\(\d+ \d+% \d+%\)$/);
    expect(palette["--background"]).toMatch(/^\d+ \d+% \d+%$/);
    expect(palette["--primary"]).toMatch(/^\d+ \d+% \d+%$/);
  });

  it("clamps an arbitrarily light background into the dark band", () => {
    const palette = deriveWorkspacePalette({
      ...FULL,
      brand_background: "#ffffff",
      brand_surface: "#f0f0f0",
    })!;
    expect(lightnessOf(palette["--background"])).toBeLessThanOrEqual(14);
    expect(lightnessOf(palette["--background"])).toBeGreaterThanOrEqual(4);
    // --aqt-bg mirrors --background (dark)
    const aqtL = Number(palette["--aqt-bg"].match(/(\d+)%\)$/)?.[1]);
    expect(aqtL).toBeLessThanOrEqual(14);
  });

  it("contrast-picks a DARK foreground on a bright accent", () => {
    const palette = deriveWorkspacePalette({ ...FULL, brand_primary: "#ffd400" })!;
    expect(palette["--primary-foreground"]).toBe("0 0% 9%");
  });

  it("contrast-picks a LIGHT foreground on a dark accent", () => {
    const palette = deriveWorkspacePalette({ ...FULL, brand_primary: "#001133" })!;
    expect(palette["--primary-foreground"]).toBe("0 0% 98%");
  });

  it("never overrides semantic role / status / chart tokens", () => {
    const palette = deriveWorkspacePalette(FULL)!;
    for (const forbidden of [
      "--aqt-tank",
      "--aqt-damage",
      "--aqt-support",
      "--aqt-emerald",
      "--aqt-amber",
      "--aqt-gold",
      "--aqt-rose",
      "--aqt-blue",
      "--chart-1",
    ]) {
      expect(palette[forbidden]).toBeUndefined();
    }
  });

  it("defaults --destructive to the standard red when not overridden", () => {
    const palette = deriveWorkspacePalette(FULL)!;
    expect(palette["--destructive"]).toBe("0 72% 51%");
  });

  it("applies curated core-palette overrides when set", () => {
    const base = deriveWorkspacePalette(FULL)!;
    const palette = deriveWorkspacePalette({
      ...FULL,
      brand_ring: "#22d3ee",
      brand_destructive: "#ef4444",
    })!;
    // set of keys is unchanged (overrides reuse existing slots)
    expect(new Set(Object.keys(palette))).toEqual(new Set(WORKSPACE_THEME_VAR_NAMES));
    // overrides win over the derived defaults
    expect(palette["--ring"]).not.toBe(base["--ring"]);
    expect(palette["--destructive"]).not.toBe("0 72% 51%");
  });

  it("ignores malformed override hex (falls back to derived)", () => {
    const base = deriveWorkspacePalette(FULL)!;
    const palette = deriveWorkspacePalette({ ...FULL, brand_ring: "nope", brand_border: "" })!;
    expect(palette["--ring"]).toBe(base["--ring"]);
    expect(palette["--border"]).toBe(base["--border"]);
  });

  it("falls back to primary/background when secondary + surface are absent", () => {
    const palette = deriveWorkspacePalette({
      ...FULL,
      brand_secondary: null,
      brand_surface: null,
    })!;
    expect(palette).not.toBeNull();
    expect(new Set(Object.keys(palette))).toEqual(new Set(WORKSPACE_THEME_VAR_NAMES));
    // secondary falls back to the (clamped) primary accent
    expect(palette["--aqt-violet"]).toBe(palette["--aqt-teal"]);
  });
});

describe("parseHex", () => {
  it("parses #RRGGBB", () => {
    expect(parseHex("#ffffff")).toEqual({ r: 255, g: 255, b: 255 });
    expect(parseHex("#000000")).toEqual({ r: 0, g: 0, b: 0 });
  });

  it("expands #RGB shorthand", () => {
    expect(parseHex("#0f8")).toEqual({ r: 0, g: 255, b: 136 });
  });

  it("rejects malformed input", () => {
    expect(parseHex("red")).toBeNull();
    expect(parseHex("#12")).toBeNull();
    expect(parseHex(null)).toBeNull();
    expect(parseHex("")).toBeNull();
  });
});

describe("rgbToHsl", () => {
  it("computes hue for a pure primary", () => {
    expect(rgbToHsl({ r: 255, g: 0, b: 0 }).h).toBeCloseTo(0, 0);
    expect(rgbToHsl({ r: 0, g: 255, b: 0 }).h).toBeCloseTo(120, 0);
    expect(rgbToHsl({ r: 0, g: 0, b: 255 }).h).toBeCloseTo(240, 0);
  });
});
