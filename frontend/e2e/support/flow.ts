import { expect, type Page } from "@playwright/test";
import type { Api } from "./api";
import { openPage } from "./fixtures";
import { listEncounters, recalcStandings, setResult } from "./flows";

export type FlowNode = { id: number; kind: string; name: string; status: string; stage_id: number | null; config: Record<string, unknown> };
export type FlowResult = { node_id: number; port: string; rank: number; workspace_member_id: number | null; team_id: number | null; state: string };
export type AdminFlow = {
  nodes: FlowNode[];
  edges: { id: number; source_node_id: number; source_port: string; target_node_id: number; target_port: string }[];
  results: FlowResult[];
  issues: { code: string }[];
};

export const adminFlow = (api: Api, tournamentId: number) => api.get<AdminFlow>(`/api/v1/admin/tournaments/${tournamentId}/flow`);

/** The node of `kind` named `name`; fails the test when the flow has none. */
export function nodeNamed(flow: AdminFlow, kind: string, name: string): FlowNode {
  const node = flow.nodes.find((n) => n.kind === kind && n.name === name);
  if (!node) throw new Error(`no ${kind} node "${name}" in the flow: ${flow.nodes.map((n) => `${n.kind} "${n.name}"`).join(", ")}`);
  return node;
}

/** The Flow tab's Presets dialog: pick `preset` by its name, fill the league's numbers, apply and save the graph. */
export async function applyPreset(page: Page, tournamentId: number, preset: string, params?: { days: number; best: number }) {
  await openPage(page, `/admin/tournaments/${tournamentId}/bracket/flow`);
  await page.getByRole("button", { name: "Presets", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: preset, exact: true }).click();
  if (params) {
    await dialog.getByLabel("Days", { exact: true }).fill(String(params.days));
    await dialog.getByLabel("Best results counted", { exact: true }).fill(String(params.best));
  }
  await dialog.getByRole("button", { name: "Apply", exact: true }).click();
  await page.getByRole("button", { name: "Save flow", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save flow", exact: true })).toHaveCount(0, { timeout: 60_000 });
}

/** `groups` round-robin groups, or one bracket, in a draft stage (`order` follows the call order). */
export async function addItems(api: Api, stageId: number, groups: number, bracket = false) {
  for (let g = 0; g < groups; g++) {
    await api.post(`/api/v1/admin/stages/${stageId}/items`, { name: `Group ${String.fromCharCode(65 + g)}`, type: "group", order: g }, 201);
  }
  if (bracket) await api.post(`/api/v1/admin/stages/${stageId}/items`, { name: "Bracket", type: "single_bracket", order: groups }, 201);
}

/**
 * Plays a stage out, 2:0 for the first seat, until a pass finds nothing left to play: a pass sets every seated, not
 * yet completed encounter, then recalculates. Several passes because rounds and bracket matches seat after the one before.
 */
export async function playOut(api: Api, tournamentId: number, stageId: number) {
  for (let pass = 0; pass < 6; pass++) {
    // A seat exists only once someone is seated in it, so two seats mean both sides are known (an individual Swiss seat has no team id).
    const open = (await listEncounters(api, tournamentId, stageId)).filter((e) => e.status !== "completed" && e.teams.length >= 2);
    if (!open.length) return;
    for (const encounter of open) await setResult(api, encounter, [2, 0]);
    await recalcStandings(api, tournamentId);
  }
}

export async function waitNode(api: Api, tournamentId: number, nodeId: number, status: string) {
  await expect
    .poll(async () => (await adminFlow(api, tournamentId)).nodes.find((n) => n.id === nodeId)?.status, { timeout: 120_000 })
    .toBe(status);
}
