import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { TournamentHistoryEntry } from "@/types/registration.types";

import TournamentHistoryCell from "./TournamentHistoryCell";

// Radix mounts tooltip content only while open; the history list is what is under test.
vi.mock("@craazzzyyfoxx/admin-kit/ui/tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: ReactNode }) => <div>{children}</div>
}));

const messages = {
  common: { roles: { flex: "Flex" }, roleOntology: { unknown: "Unknown role: {role}", retired: "Retired role: {role}" }, divisionWithId: "Division {id}", more: "more" },
  tournamentDetail: { newBadge: "New", previousTournaments: "{count} previous" }
};

const WORKSPACE = 7;

/** The workspace's Overwatch dictionary plus one workspace child of `damage` with its own name and artwork. */
const OW = {
  ...OW_METADATA,
  workspace_id: WORKSPACE,
  roles: [
    ...OW_METADATA.roles,
    {
      id: 20,
      dimension: "player_role",
      code: "damage_hitscan",
      name: "Hitscan",
      parent_id: 2,
      workspace_id: WORKSPACE,
      active: true,
      selectable: true,
      sort_order: 20,
      attrs: { icon: "/test-roles/hitscan.svg" }
    }
  ]
};

/** Metadata the workspace has already read: both installed games, nothing for anything else. */
function render(discipline: string, role: TournamentHistoryEntry["role"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(disciplineQueryKeys.metadata(WORKSPACE, "overwatch"), OW);
  client.setQueryData(disciplineQueryKeys.metadata(WORKSPACE, "lol"), { ...LOL_METADATA, workspace_id: WORKSPACE });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <TournamentHistoryCell
          history={[{ tournament_id: 1, tournament_name: "Autumn Cup", discipline, role, division: null }]}
          workspaceId={WORKSPACE}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

describe("TournamentHistoryCell", () => {
  it("names and draws the exact historical leaf, not its parent", () => {
    const markup = render("overwatch", { dimension: "player_role", role: "damage_hitscan", parent: "damage" });

    expect(markup).toContain("Hitscan");
    expect(markup).toContain("/test-roles/hitscan.svg");
    // The parent's own name and artwork are not what this participation was played as.
    expect(markup).not.toContain(">Damage<");
    expect(markup).not.toContain("/test-roles/damage.svg");
  });

  it("still resolves a plain root assignment through the dictionary", () => {
    const markup = render("overwatch", { dimension: "player_role", role: "damage" });

    expect(markup).toContain(">Damage<");
    expect(markup).toContain("/test-roles/damage.svg");
  });

  it("draws another game's past tournament in that game's own ontology", () => {
    const markup = render("lol", { dimension: "position", role: "mid" });

    expect(markup).toContain(">Mid<");
    expect(markup).toContain("/test-roles/mid.svg");
    expect(markup).not.toContain("Unknown role");
  });

  it("keeps a role of a game whose metadata is unknown neutral, by its own code", () => {
    const markup = render("dota", { dimension: "position", role: "mid" });

    expect(markup).toContain(">mid<");
    expect(markup).toContain("Unknown role: mid");
    expect(markup).not.toContain("/test-roles/");
  });
});
