import type { FilterFn, Row } from "@tanstack/react-table";
import { describe, expect, it } from "vitest";

import { readAdminColumnMeta, readAdminColumnFilter } from "@/components/admin-data-table";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { CustomFieldDefinition, StatusMeta } from "@/types/registration.types";

import { buildBalancerRegistrationColumns } from "./balancerRegistrationColumns";

const CUSTOM_FIELDS: CustomFieldDefinition[] = [
  { key: "vk", label: "VK profile", type: "text", required: false, placeholder: null, options: null },
  {
    key: "rules",
    label: "Read the rules",
    type: "checkbox",
    required: true,
    placeholder: null,
    options: null,
  },
];

function registration(overrides: Partial<AdminRegistration> = {}): AdminRegistration {
  return {
    id: 1,
    battle_tag: "Player#1234",
    display_name: "Player",
    discord_nick: "player",
    twitch_nick: "player_tv",
    boosty_nick: "player_boosty",
    smurf_tags_json: [],
    custom_fields_json: null,
    source: "manual",
    source_record_key: null,
    ...overrides,
  } as unknown as AdminRegistration;
}

function column(id: string, ...args: Parameters<typeof buildBalancerRegistrationColumns>) {
  const found = buildBalancerRegistrationColumns(...args).find((candidate) => candidate.id === id);
  if (!found) {
    throw new Error(`No "${id}" column was built`);
  }

  return found;
}

describe("balancer registration column model", () => {
  it("builds one column per custom-field definition", () => {
    // The admin table rendered no custom fields at all: an organizer could read
    // an answer nowhere and fix it nowhere.
    const ids = buildBalancerRegistrationColumns(undefined, false, CUSTOM_FIELDS).map(
      (candidate) => candidate.id,
    );

    expect(ids).toContain("custom_vk");
    expect(ids).toContain("custom_rules");
  });

  it("reads the stored answer for its own definition", () => {
    const vk = column("custom_vk", undefined, false, CUSTOM_FIELDS);
    const meta = readAdminColumnMeta<AdminRegistration>(vk.meta);

    const value = meta.searchValue?.(registration({ custom_fields_json: { vk: "vk.com/player" } }));
    expect(value).toBe("vk.com/player");
  });

  it("adds no custom columns when the form defines none", () => {
    const ids = buildBalancerRegistrationColumns().map((candidate) => candidate.id);

    expect(ids.some((id) => id?.startsWith("custom_"))).toBe(false);
  });

  it("searches the participant by every handle, boosty included", () => {
    const meta = readAdminColumnMeta<AdminRegistration>(column("participant").meta);

    expect(meta.searchValue?.(registration())).toContain("player_boosty");
  });

  it("offers the status values the caller collected, not a hardcoded list", () => {
    // Statuses are workspace-configurable, so a literal list in the column would
    // hide every custom one an organizer added.
    const statusOptions = [
      { value: "pending", label: "Pending" },
      { value: "shortlisted", label: "Shortlisted" },
    ];

    const filter = readAdminColumnFilter(
      column("status", undefined, false, [], statusOptions).meta,
    );

    expect(filter?.param).toBe("status");
    expect(filter?.options).toEqual(statusOptions);
  });

  it("splits the balancer pool from the rows it excludes", () => {
    const balancer = column("balancer");
    const filterFn = balancer.filterFn as FilterFn<AdminRegistration>;
    const excludedRow = {
      original: registration({
        balancer_status: "excluded",
        balancer_status_meta: { excludes_from_balancer: true } as StatusMeta,
      }),
    } as Row<AdminRegistration>;

    expect(filterFn(excludedRow, "balancer", ["excluded"], () => {})).toBe(true);
    expect(filterFn(excludedRow, "balancer", ["included"], () => {})).toBe(false);
  });
});
