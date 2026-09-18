import { describe, expect, it } from "vitest";

import type { RegistrationForm } from "@/types/registration.types";

import { buildParticipantColumns } from "./participantsColumns";

const t = ((key: string) => key) as never;

function form(overrides: Partial<RegistrationForm> = {}): RegistrationForm {
  return {
    id: 1,
    tournament_id: 72,
    workspace_id: 1,
    is_open: true,
    built_in_fields: {},
    custom_fields: [],
    ...overrides,
  };
}

describe("participant column model", () => {
  it("keeps identity and status mandatory when the form disables BattleTag", () => {
    const columns = buildParticipantColumns(
      form({
        built_in_fields: {
          battle_tag: { enabled: false, required: false },
          notes: { enabled: true, required: false },
        },
      }),
      t,
    );

    expect(
      columns.filter((column) => ["battle_tag", "_status"].includes(column.id)).map((column) => column.id),
    ).toEqual(["battle_tag", "_status"]);
  });

  it("always offers the notes column even when the form omits or disables it", () => {
    const baseForm = form({ built_in_fields: { battle_tag: { enabled: true, required: true } } });
    const disabledNotesForm = form({
      built_in_fields: {
        battle_tag: { enabled: true, required: true },
        notes: { enabled: false, required: false },
      },
    });

    for (const candidate of [baseForm, disabledNotesForm, null]) {
      const notesColumns = buildParticipantColumns(candidate, t).filter((column) => column.id === "notes");
      expect(notesColumns).toHaveLength(1);
      expect(notesColumns[0].defaultVisible).toBe(true);
    }
  });

  it("offers a column for every identity handle the form collects", () => {
    // Boosty was the one handle with a form field, a column-worthy value and no
    // column, so the roster could never show it.
    const columns = buildParticipantColumns(
      form({
        built_in_fields: {
          battle_tag: { enabled: true, required: true },
          discord_nick: { enabled: true, required: false },
          twitch_nick: { enabled: true, required: false },
          boosty_nick: { enabled: true, required: false },
        },
      }),
      t,
    );

    const ids = columns.map((column) => column.id);
    expect(ids).toContain("discord_nick");
    expect(ids).toContain("twitch_nick");
    expect(ids).toContain("boosty_nick");
  });

  it("reads the boosty handle off the registration", () => {
    const [boosty] = buildParticipantColumns(
      form({ built_in_fields: { boosty_nick: { enabled: true, required: false } } }),
      t,
    ).filter((column) => column.id === "boosty_nick");

    expect(boosty.searchValue?.({ boosty_nick: "player_boosty" } as never)).toBe("player_boosty");
  });

  it("builds one column per custom-field definition and reads its stored answer", () => {
    const columns = buildParticipantColumns(
      form({
        custom_fields: [
          { key: "vk", label: "VK profile", type: "text", required: false, options: null },
        ],
      }),
      t,
    );

    const custom = columns.find((column) => column.id === "custom_vk");
    expect(custom?.label).toBe("VK profile");
    expect(custom?.searchValue?.({ custom_fields_json: { vk: "vk.com/player" } } as never)).toBe(
      "vk.com/player",
    );
  });

  it("offers the team column off by default until the roster actually carries teams", () => {
    // A solo tournament leaves every team cell empty, so the column must stay out
    // of the default set; on a team tournament it must be ON, because search only
    // walks visible columns and finding players by team is the point of it.
    const withoutTeams = buildParticipantColumns(form(), t).find((column) => column.id === "team");
    const withTeams = buildParticipantColumns(form(), t, "ru", null, undefined, true).find(
      (column) => column.id === "team",
    );

    expect(withoutTeams?.defaultVisible).toBe(false);
    expect(withTeams?.defaultVisible).toBe(true);
    expect(
      withTeams?.searchValue?.({
        team: { id: 3, name: "Ночные совы", status: "forming", slot_code: "damage", is_substitute: false, is_captain: true },
      } as never),
    ).toBe("Ночные совы");
    expect(withTeams?.searchValue?.({} as never)).toBeNull();
    expect(withTeams?.render({} as never, 0)).toBeNull();
  });
});
