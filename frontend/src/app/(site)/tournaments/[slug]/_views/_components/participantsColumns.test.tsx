import { describe, expect, it } from "vitest";

import type { FormField } from "@/types/forms.types";
import type { RegistrationForm } from "@/types/registration.types";

import { buildParticipantColumns } from "./participantsColumns";

const t = ((key: string) => key) as never;

function field(key: string, overrides: Partial<FormField> = {}): FormField {
  return {
    key,
    kind: "builtin",
    required: false,
    visibility: "public",
    params: {},
    show_in_draft: false,
    ...overrides,
  };
}

function form(fields: FormField[] = []): RegistrationForm {
  return {
    id: 1,
    tournament_id: 72,
    workspace_id: 1,
    is_open: true,
    form_schema: { schema_version: 1, sections: [{ key: "main", fields }] },
    version_id: 9,
    version_number: 1,
  };
}

describe("participant column model", () => {
  it("keeps identity and status mandatory when the form does not ask for a BattleTag", () => {
    const columns = buildParticipantColumns(form([field("public_notes")]), t);

    expect(
      columns.filter((column) => ["battle_tag", "_status"].includes(column.id)).map((column) => column.id),
    ).toEqual(["battle_tag", "_status"]);
  });

  it("always offers the notes column even when the form does not ask for notes", () => {
    for (const candidate of [form([field("battle_tag")]), form(), null]) {
      const notesColumns = buildParticipantColumns(candidate, t).filter(
        (column) => column.id === "public_notes",
      );
      expect(notesColumns).toHaveLength(1);
      expect(notesColumns[0].defaultVisible).toBe(true);
    }
  });

  it("offers a column for every identity handle the form collects", () => {
    const columns = buildParticipantColumns(
      form([
        field("battle_tag"),
        field("identity_discord"),
        field("identity_twitch"),
        field("identity_boosty"),
      ]),
      t,
    );

    const ids = columns.map((column) => column.id);
    expect(ids).toContain("identity_discord");
    expect(ids).toContain("identity_twitch");
    expect(ids).toContain("identity_boosty");
  });

  it("reads the boosty handle off the registration's answers", () => {
    const [boosty] = buildParticipantColumns(form([field("identity_boosty")]), t).filter(
      (column) => column.id === "identity_boosty",
    );

    expect(boosty.searchValue?.({ answers: { identity_boosty: "player_boosty" } } as never)).toBe(
      "player_boosty",
    );
  });

  it("leaves an organizers-only question off the public roster entirely", () => {
    // A public read carries no organizers-only answer, so such a column could
    // only ever be empty — and its header would advertise a question whose
    // answers the reader is not allowed to have.
    const ids = buildParticipantColumns(
      form([
        field("battle_tag"),
        field("organizer_notes", { visibility: "organizers" }),
        field("budget", { kind: "text", label: "Budget", visibility: "organizers" }),
      ]),
      t,
    ).map((column) => column.id);

    expect(ids).not.toContain("organizer_notes");
    expect(ids).not.toContain("budget");
  });

  it("builds one column per organizer-defined question and reads its stored answer", () => {
    const columns = buildParticipantColumns(
      form([field("vk", { kind: "text", label: "VK profile" })]),
      t,
    );

    const custom = columns.find((column) => column.id === "vk");
    expect(custom?.label).toBe("VK profile");
    expect(custom?.searchValue?.({ answers: { vk: "vk.com/player" } } as never)).toBe(
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
