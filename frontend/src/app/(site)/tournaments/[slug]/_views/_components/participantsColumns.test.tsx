import React from "react";
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import en from "@/i18n/messages/en.json";
import { canonicalDisplay } from "@/lib/player";
import type { FormField } from "@/types/forms.types";
import type { RegistrationForm } from "@/types/registration.types";

import { DEADLOCK_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import { buildParticipantColumns } from "./participantsColumns";

const t = ((key: string) => key) as never;

const OWNER = { discipline: "overwatch", identityProvider: "battlenet", ontology: null };
const LOL_OWNER = { discipline: "lol", identityProvider: "riot", ontology: null };

function field(key: string, overrides: Partial<FormField> = {}): FormField {
  return {
    key,
    kind: "builtin",
    required: false,
    visibility: "public",
    params: {},
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
    const columns = buildParticipantColumns(form([field("public_notes")]), t, OWNER);

    expect(
      columns.filter((column) => ["_identity", "_status"].includes(column.id)).map((column) => column.id),
    ).toEqual(["_identity", "_status"]);
  });

  it("always offers the notes column even when the form does not ask for notes", () => {
    for (const candidate of [form([field("identity_battlenet")]), form(), null]) {
      const notesColumns = buildParticipantColumns(candidate, t, OWNER).filter(
        (column) => column.id === "public_notes",
      );
      expect(notesColumns).toHaveLength(1);
      expect(notesColumns[0].defaultVisible).toBe(true);
    }
  });

  it("offers a column for every identity handle the form collects", () => {
    const columns = buildParticipantColumns(
      form([
        field("identity_battlenet"),
        field("identity_discord"),
        field("identity_twitch"),
        field("identity_boosty"),
      ]),
      t, OWNER,
    );

    const ids = columns.map((column) => column.id);
    expect(ids).toContain("identity_discord");
    expect(ids).toContain("identity_twitch");
    expect(ids).toContain("identity_boosty");
  });

  it("builds no generic answer column for a game account while the owner's metadata is pending or failed", () => {
    // Pending and failed metadata both reach the builder as an owner without a provider. The generic answer
    // renderer prints a whole handle list, alternates included, and the public roster filter only removes
    // `_identity_extras`: so a game account must have NO column at all until the owner resolves.
    const asked = form([field("identity_battlenet"), field("identity_riot"), field("identity_discord")]);
    const unresolved = { discipline: "overwatch", identityProvider: null, ontology: null };
    const ids = buildParticipantColumns(asked, t, unresolved).map((column) => column.id);

    for (const leaked of ["identity_battlenet", "identity_riot", "_identity", "_identity_extras"]) {
      expect(ids).not.toContain(leaked);
    }
    // A social handle is not a game account: it keeps its ordinary column.
    expect(ids).toContain("identity_discord");
  });

  it("splits the Battle.net answer into the primary handle and the extra handles", () => {
    const columns = buildParticipantColumns(form([field("identity_battlenet")]), t, OWNER);
    const identity = columns.find((column) => column.id === "_identity");
    const extras = columns.find((column) => column.id === "_identity_extras");
    const registration = {
      primary_handle: "Main#1111",
      display: canonicalDisplay("Main#1111"),
      answers: { identity_battlenet: ["Main#1111", "Alt#2222", "Alt#3333"] },
    } as never;

    expect(identity?.searchValue?.(registration)).toBe("Main#1111");
    expect(extras?.searchValue?.(registration)).toBe("Alt#2222 Alt#3333");
  });

  it("offers no extra-handle column when the form allows a single BattleTag", () => {
    const ids = buildParticipantColumns(
      form([field("identity_battlenet", { params: { max_count: 1 } })]),
      t, OWNER,
    ).map((column) => column.id);

    expect(ids).not.toContain("_identity_extras");
  });

  it("reads the boosty handle off the registration's answers", () => {
    const [boosty] = buildParticipantColumns(form([field("identity_boosty")]), t, OWNER).filter(
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
        field("identity_battlenet"),
        field("organizer_notes", { visibility: "organizers" }),
        field("budget", { kind: "text", label: "Budget", visibility: "organizers" }),
      ]),
      t, OWNER,
    ).map((column) => column.id);

    expect(ids).not.toContain("organizer_notes");
    expect(ids).not.toContain("budget");
  });

  it("invents no columns for a form that asks the public nothing", () => {
    // No invariant makes `identity_battlenet` mandatory and every question may
    // be organizers-only, so this is a configured form with an empty public
    // side — not the "no form at all" case, and it must not be given that
    // case's roles/heroes/smurfs columns.
    const ids = buildParticipantColumns(
      form([field("organizer_notes", { visibility: "organizers" })]),
      t, OWNER,
    ).map((column) => column.id);

    for (const invented of ["roles", "top_heroes", "_identity_extras"]) {
      expect(ids).not.toContain(invented);
    }
    // The roster's own identity column and the notes column stay: the first is
    // a registration column rather than an answer, the second may hold what a
    // sheet import wrote.
    expect(ids).toContain("_identity");
    expect(ids).toContain("public_notes");
  });

  it("builds one column per organizer-defined question and reads its stored answer", () => {
    const columns = buildParticipantColumns(
      form([field("vk", { kind: "text", label: "VK profile" })]),
      t, OWNER,
    );

    const custom = columns.find((column) => column.id === "vk");
    expect(custom?.label).toBe("VK profile");
    expect(custom?.searchValue?.({ answers: { vk: "vk.com/player" } } as never)).toBe(
      "vk.com/player",
    );
  });

  it("builds the team column only when the roster actually carries teams", () => {
    // A solo tournament leaves every team cell empty, so the column must not
    // exist at all: a hidden column still prints a blank "Team" row in every
    // expanded details panel. On a team tournament it must be ON, because
    // search only walks visible columns and finding players by team is the
    // point of it.
    const withoutTeams = buildParticipantColumns(form(), t, OWNER).find((column) => column.id === "team");
    const withTeams = buildParticipantColumns(form(), t, OWNER, null, undefined, true).find(
      (column) => column.id === "team",
    );

    expect(withoutTeams).toBeUndefined();
    expect(withTeams?.defaultVisible).toBe(true);
    expect(
      withTeams?.searchValue?.({
        team: { id: 3, name: "Ночные совы", status: "forming", slot_code: "damage", is_substitute: false, is_captain: true },
      } as never),
    ).toBe("Ночные совы");
    expect(withTeams?.searchValue?.({} as never)).toBeNull();
    expect(withTeams?.render({} as never, 0)).toBeNull();
  });

  it("marks the status cell late, and never stacks the on-call answer on it", () => {
    // Lateness is the schedule's own mark and belongs beside the status. The
    // registrant's "you can call me in" is organizer bookkeeping: under every
    // Pending pill it read as a second status the player was in.
    const status = buildParticipantColumns(form(), t, OWNER).find((column) => column.id === "_status")!;
    const render = (reg: unknown) =>
      renderToStaticMarkup(
        <NextIntlClientProvider locale="en" messages={en}>
          {status.render(reg as never, 0)}
        </NextIntlClientProvider>,
      );

    const late = render({ status: "approved", answers: { reserve: true }, submitted_late: true });
    const plain = render({ status: "approved", answers: { reserve: true }, submitted_late: false });

    expect(late).toContain('data-row-late="true"');
    expect(plain).not.toContain("data-row-late");
    expect(late).not.toContain("data-row-on-call");
  });

  it("offers the on-call answer as its own column, off by default", () => {
    // Asked as a question, so it rides the schema like any other answer: the
    // reader turns it on when they care who can be rung.
    const onCall = buildParticipantColumns(form([field("reserve")]), t, OWNER).find(
      (column) => column.id === "reserve",
    );

    expect(onCall?.defaultVisible).toBe(false);
    expect(onCall?.label).toBe("registration.details.reserve");
  });

  it("names the roster's identity from the owner game's provider, never Battle.net", () => {
    const columns = buildParticipantColumns(
      form([field("identity_riot"), field("identity_battlenet")]),
      t,
      LOL_OWNER
    );
    const identity = columns.find((column) => column.id === "_identity");
    // The Riot question IS the identity column; the Battle.net answer of the same form is an ordinary column.
    expect(identity?.label).toBe("registration.accounts.riot");
    expect(columns.filter((column) => column.id === "_identity")).toHaveLength(1);
    expect(columns.some((column) => column.id === "identity_riot")).toBe(false);
    expect(columns.some((column) => column.id === "identity_battlenet")).toBe(true);
    const markup = renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={en}>
        {identity?.render(
          { primary_handle: "Faker#KR1", display: canonicalDisplay("Faker#KR1"), answers: {} } as never,
          0
        )}
      </NextIntlClientProvider>
    );
    // The name and its muted tag, linked by the canonical name.
    expect(markup).toContain("Faker");
    expect(markup).toContain("#KR1");
    expect(markup).toContain('href="/users/Faker-KR1"');
  });

  it("builds no identity column while the owner provider is unresolved", () => {
    const ids = buildParticipantColumns(
      form([field("identity_riot")]),
      t,
      { discipline: "lol", identityProvider: null, ontology: null }
    ).map((column) => column.id);
    expect(ids).not.toContain("_identity");
  });

  it("builds no roles column for a one-role game, and keeps it for a game with several", () => {
    const asksRoles = form([field("roles", { params: { top_heroes: { enabled: true, required: false, max: 3 } } })]);
    for (const candidate of [asksRoles, null]) {
      const deadlock = buildParticipantColumns(candidate, t, {
        discipline: "deadlock",
        identityProvider: "steam",
        ontology: DEADLOCK_METADATA,
      }).map((column) => column.id);
      expect(deadlock).not.toContain("roles");
      // The heroes a player brings still say something when every player has the same role.
      expect(deadlock).toContain("top_heroes");

      const overwatch = buildParticipantColumns(candidate, t, { ...OWNER, ontology: OW_METADATA }).map(
        (column) => column.id,
      );
      expect(overwatch).toContain("roles");
    }
  });
});
