import { cache } from "react";

import workspaceService from "@/services/workspace.service";
import { isTenantHost } from "@/lib/site/tenant-host";

// Both of these are asked for by half a dozen independent sections of this
// page. `cache()` collapses them to one header read / one HTTP request per
// render instead of seven and two.
export const getTenantMode = cache(isTenantHost);
export const getWorkspaces = cache(() => workspaceService.getAll());

// Deterministic accent per workspace, cycled over the palette tokens so a
// workspace theme can retint it. This used to be a raw HSL hue rotation.
const WORKSPACE_ACCENTS = [
  "--aqt-teal",
  "--aqt-blue",
  "--aqt-amber",
  "--aqt-violet",
  "--aqt-emerald",
  "--aqt-rose"
] as const;

export function workspaceAccent(id: number): string {
  return `var(${WORKSPACE_ACCENTS[id % WORKSPACE_ACCENTS.length]})`;
}

export function accentTint(accent: string, percent: number): string {
  return `color-mix(in srgb, ${accent} ${percent}%, transparent)`;
}

/** Focus ring for the whole-card links (event cards, workspace cards). */
export const CARD_LINK_FOCUS =
  "rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]";
