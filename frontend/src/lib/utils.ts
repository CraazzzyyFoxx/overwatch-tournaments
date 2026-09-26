import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The type-role utilities (`@theme` in globals.css). Without this, tailwind-merge
// files `text-label` under text-COLOR and a later `text-[color:…]` deletes it.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["label", "caption", "body", "ui", "heading", "title", "headline", "display"] }],
      tracking: [{ tracking: ["label"] }]
    }
  }
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * `aria-sort` for a sortable column header, from either a TanStack column's
 * `getIsSorted()` (`false | "asc" | "desc"`) or a hand-rolled sort state's
 * direction. Non-sortable columns must omit the attribute entirely rather than
 * report `"none"`, so that decision stays at the call site.
 */
export function ariaSortValue(
  direction: "asc" | "desc" | false | null | undefined
): "ascending" | "descending" | "none" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}

/**
 * Avatar-fallback initials. One implementation for every surface — this used to
 * be copy-pasted seven times with subtly different letters for the same person.
 *
 * A battletag suffix (`Karnage#22778`) is noise, so it is dropped before
 * splitting; a single-word name contributes its first `max` letters, a
 * multi-word one the first letter of its first `max` words.
 */
export function initials(name: string | null | undefined, max = 2): string {
  const parts = (name ?? "")
    .replace(/#.*$/, "")
    .split(/[\s_-]+/)
    .filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, max).toUpperCase();
  return parts
    .slice(0, max)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

export function hexToRgba(hex: string, alpha: number): string | null {
  const normalized = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    return null;
  }

  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

