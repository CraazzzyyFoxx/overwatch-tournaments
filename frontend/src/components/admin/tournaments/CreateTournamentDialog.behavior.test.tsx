// @vitest-environment happy-dom
//
// "Create tournament" creates the tournament Unpublished in one request (two for a Challonge import, whose
// endpoint takes neither visibility nor formation) and hands it to the caller. A Challonge import that cannot be
// hidden afterwards must still hand it over: failing the create there would invite a retry that imports twice.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { Tournament } from "@/types/tournament.types";

import { CreateTournamentDialog } from "./CreateTournamentDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const { service, warning } = vi.hoisted(() => ({
  service: { createTournament: vi.fn(), createTournamentWithGroups: vi.fn(), updateTournament: vi.fn() },
  warning: vi.fn()
}));

vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/services/admin.service", () => ({ default: service }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), warning, apiError: vi.fn() } }));
// The calendar popover is not the subject: a stand-in that picks a fixed range.
vi.mock("@/components/ui/date-range-picker", () => ({
  DateRangePicker: ({ onChange }: { onChange: (start: string, end: string) => void }) => (
    <button type="button" onClick={() => onChange("2026-11-01", "2026-11-03")}>
      pick dates
    </button>
  )
}));

const created = { id: 41 } as Tournament;
const onCreated = vi.fn();
let root: Root;
let container: HTMLDivElement;

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("nothing to click");
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise<void>((done) => setTimeout(done, 0));
  });
}

const byText = (selector: string, text: string) =>
  [...document.querySelectorAll(selector)].find((node) => node.textContent?.trim() === text);

async function type(id: string, value: string) {
  const input = document.getElementById(id) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const submit = () => click(byText("button", "Create tournament"));

beforeEach(async () => {
  for (const fn of [...Object.values(service), warning, onCreated]) fn.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <CreateTournamentDialog
            workspaceId={7}
            games={[OW_METADATA.discipline, LOL_METADATA.discipline]}
            defaultGame="overwatch"
            onClose={() => {}}
            onCreated={onCreated}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>
    )
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("CreateTournamentDialog", () => {
  it("refuses a blank name and missing dates, naming both, and sends nothing", async () => {
    // Whitespace passes the input's native `required`; only the dialog's own check catches it.
    await type("create-tournament-name", "   ");
    await submit();

    const alert = document.querySelector('[role="alert"]')?.textContent ?? "";
    expect(alert).toContain("Enter a tournament name.");
    expect(alert).toContain("Pick a start and an end date.");
    expect(service.createTournament).not.toHaveBeenCalled();
  });

  it("creates the tournament Unpublished in the picked game and hands it over", async () => {
    service.createTournament.mockResolvedValue(created);

    await click(document.getElementById("create-tournament-game"));
    await click(byText('[role="option"]', "LoLLeague of Legends"));
    await type("create-tournament-name", "  Autumn Cup ");
    await click(byText("button", "pick dates"));
    await submit();

    expect(service.createTournament).toHaveBeenCalledWith({
      workspace_id: 7,
      discipline: "lol",
      name: "Autumn Cup",
      is_hidden: true,
      team_formation: "balancer",
      start_date: "2026-11-01",
      end_date: "2026-11-03"
    });
    expect(onCreated).toHaveBeenCalledWith(created);
  });

  it("imports from Challonge once and still hands the import over when hiding it fails", async () => {
    const imported = { id: 42 } as Tournament;
    service.createTournamentWithGroups.mockResolvedValue(imported);
    service.updateTournament.mockRejectedValue(new Error("down"));

    await click(document.querySelector('[role="radio"][aria-labelledby="create-tournament-source-challonge-title"]'));
    await type("create-tournament-challonge", "https://challonge.com/my-cup");
    await click(byText("button", "pick dates"));
    await submit();

    expect(service.createTournamentWithGroups).toHaveBeenCalledTimes(1);
    expect(service.createTournamentWithGroups).toHaveBeenCalledWith(
      expect.objectContaining({ workspace_id: 7, discipline: "overwatch", challonge_slug: "my-cup" })
    );
    expect(service.updateTournament).toHaveBeenCalledWith(42, { is_hidden: true, team_formation: "balancer" });
    expect(warning).toHaveBeenCalledOnce();
    expect(onCreated).toHaveBeenCalledWith(imported);
  });
});
