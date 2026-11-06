// @vitest-environment happy-dom
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { DraftNode } from "@/lib/flow/flowDraft";

import { NodeInspector } from "./NodeInspector";

vi.mock("@/components/tournaments/FlowNodeControls", () => ({ FlowNodeControls: ({ node }: { node: { id: number } }) => <p>controls {node.id}</p> }));
vi.mock("../../settings/registration/RegistrationNodeSettingsForm", () => ({ RegistrationNodeSettingsForm: ({ node }: { node: { id: number } }) => <p>settings {node.id}</p> }));
vi.mock("../../settings/schedule/NodeScheduleEditor", () => ({ NodeScheduleEditor: ({ node }: { node: { id: number } }) => <p>schedule {node.id}</p> }));
vi.mock("@/components/balancer/registrations/RegistrationsTable", () => ({ default: ({ registrationNodeId }: { registrationNodeId: number }) => <p>entries {registrationNodeId}</p> }));
vi.mock("../../components/DraftSessionDashboard", () => ({ DraftSessionDashboard: ({ formationNodeId }: { formationNodeId: number }) => <p>draft {formationNodeId}</p> }));
vi.mock("../../bracket/useBracketTabData", () => ({ useBracketTabData: () => ({ orderedStages: [{ id: 40, name: "Groups" }], progressByStageId: new Map(), teams: [], isTeamsLoading: false, tournamentQuery: { data: undefined } }) }));
vi.mock("../../bracket/components/StageEditor", () => ({ StageEditor: ({ stage }: { stage: { id: number } }) => <p>stage editor {stage.id}</p> }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true, isSuperuser: true }) }));
vi.mock("@tanstack/react-query", async (orig) => ({ ...(await orig<typeof import("@tanstack/react-query")>()), useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const tournament = {
  id: 7,
  workspace_id: 3,
  flow_nodes: [
    { id: 1, kind: "registration", name: "Day 1", status: "open", stage_id: null, config: {}, schedule: [], pool_registration_node_ids: [] },
    { id: 2, kind: "formation", name: "Day 1 teams", status: "draft", stage_id: null, config: { mode: "draft" }, schedule: [], pool_registration_node_ids: [1] },
    { id: 3, kind: "stage", name: "Groups", status: "draft", stage_id: 40, config: {}, schedule: [], pool_registration_node_ids: [] }
  ]
} as never;
const node = (over: Partial<DraftNode>): DraftNode => ({ key: "1", id: 1, kind: "registration", name: "Day 1", config: {}, stageId: null, stage: null, x: 0, y: 0, status: "open", ...over });

let root: Root;
let container: HTMLDivElement;
async function render(n: DraftNode, dirty = false) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <NodeInspector tournamentId={7} tournament={tournament} node={n} dirty={dirty} readOnly={false} onChange={vi.fn()} onClose={vi.fn()} />
      </NextIntlClientProvider>
    );
  });
  await act(() => new Promise((r) => setTimeout(r, 0)));
}
const unmount = () => {
  act(() => root.unmount());
  container.remove();
};
afterEach(unmount);

describe("lifecycle node inspectors", () => {
  it("a registration node embeds its settings, schedule, controls and entries", async () => {
    await render(node({}));
    for (const text of ["controls 1", "settings 1", "schedule 1", "entries 1"]) expect(container.textContent).toContain(text);
  });

  it("an unsaved lifecycle node asks for a save, and a dirty graph hides the embedded forms", async () => {
    await render(node({ key: "new-1", id: null, status: null }));
    expect(container.textContent).toContain("Save the flow to configure this node.");
    unmount();
    await render(node({}), true);
    expect(container.textContent).toContain("Save or discard the graph first.");
    expect(container.textContent).not.toContain("settings 1");
  });

  it("a formation embeds the draft by mode, or links the balancer with its node", async () => {
    await render(node({ key: "2", id: 2, kind: "formation", name: "Day 1 teams", status: "draft", config: { mode: "draft" } }));
    expect(container.textContent).toContain("draft 2");
    unmount();
    await render(node({ key: "2", id: 2, kind: "formation", status: "draft", config: { mode: "balancer" } }));
    expect(container.querySelector('a[href="/balancer?tournament=7&node=2"]')).not.toBeNull();
  });

  it("a stage node embeds the stage editor of its stage", async () => {
    await render(node({ key: "3", id: 3, kind: "stage", name: "Groups", stageId: 40, status: "draft" }));
    expect(container.textContent).toContain("stage editor 40");
  });
});
