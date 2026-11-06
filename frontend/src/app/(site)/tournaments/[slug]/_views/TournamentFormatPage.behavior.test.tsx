// @vitest-environment happy-dom
//
// The public Format tab draws the tournament's flow read-only: every node with its status.
// The canvas is stubbed: this file pins what the page hands it, not xyflow's drawing.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { leagueFlow } from "@/lib/flow/fixtures";

import TournamentFormatPage from "./TournamentFormatPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: { id: 7, slug: "t", status: "live" } })
}));
vi.mock("@/services/flow.service", () => ({
  default: { get: () => Promise.resolve(leagueFlow()) }
}));
vi.mock("@/components/flow/FlowCanvas", () => ({
  FlowCanvas: ({
    nodes,
    readOnly
  }: {
    nodes: { data: { name: string; status: string } }[];
    readOnly: boolean;
  }) => (
    <ul>
      {nodes.map((n, i) => (
        <li key={i}>
          {n.data.name} · {n.data.status} · {String(readOnly)}
        </li>
      ))}
    </ul>
  )
}));

let root: Root;
let container: HTMLDivElement;

async function mount(ui: React.ReactElement) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          {ui}
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("public Format tab", () => {
  it("draws the public flow read-only, every node with its status", async () => {
    await mount(<TournamentFormatPage slug="t" />);
    const items = [...container.querySelectorAll("li")].map((li) => li.textContent);
    expect(items).toContain("Day 1 · completed · true");
    expect(items).toContain("Season table · final · true");
    expect(container.textContent).toContain(
      "Each box is a step of the tournament; arrows show who moves on."
    );
  });
});
