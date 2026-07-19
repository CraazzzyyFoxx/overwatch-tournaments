import { describe, expect, it } from "bun:test";

import type { RegistrationForm } from "@/types/registration.types";

import { buildParticipantColumns } from "./participantsColumns";

describe("participant column model", () => {
  it("keeps identity and status mandatory when the form disables BattleTag", () => {
    const form: RegistrationForm = {
      id: 1,
      tournament_id: 72,
      workspace_id: 1,
      is_open: true,
      built_in_fields: {
        battle_tag: { enabled: false, required: false },
        notes: { enabled: true, required: false },
      },
      custom_fields: [],
    };
    const t = ((key: string) => key) as never;

    const columns = buildParticipantColumns(form, t);

    expect(columns.filter((column) => ["battle_tag", "_status"].includes(column.id)).map((column) => column.id)).toEqual([
      "battle_tag",
      "_status",
    ]);
  });

  it("always offers the notes column even when the form omits or disables it", () => {
    const baseForm: RegistrationForm = {
      id: 1,
      tournament_id: 72,
      workspace_id: 1,
      is_open: true,
      built_in_fields: {
        battle_tag: { enabled: true, required: true },
      },
      custom_fields: [],
    };
    const disabledNotesForm: RegistrationForm = {
      ...baseForm,
      built_in_fields: {
        battle_tag: { enabled: true, required: true },
        notes: { enabled: false, required: false },
      },
    };
    const t = ((key: string) => key) as never;

    for (const form of [baseForm, disabledNotesForm, null]) {
      const notesColumns = buildParticipantColumns(form, t).filter(
        (column) => column.id === "notes",
      );
      expect(notesColumns).toHaveLength(1);
      expect(notesColumns[0].defaultVisible).toBe(true);
    }
  });
});
