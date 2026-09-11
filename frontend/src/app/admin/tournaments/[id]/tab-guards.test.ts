import { describe, expect, test } from "vitest";

import {
  allowedSettingsSection,
  allowedTab,
  allowedTeamsSubTab,
  isLegacyTabSegment,
  isTabKey,
  MATCHES_SUB_TABS,
  REGISTRATION_SUB_TABS,
  SETTINGS_SECTIONS,
  TAB_KEYS,
  TEAMS_SUB_TABS,
  type SettingsSection,
  type TabKey
} from "./tab-guards";

const NO_PERMS = {
  canUpdateTournament: false,
  canUpdateEncounter: false,
  canTeamRead: false,
  canReadTournamentLink: false,
  canDeleteTournament: false,
  teamFormation: "balancer"
} as const;

const ALL_PERMS = {
  canUpdateTournament: true,
  canUpdateEncounter: true,
  canTeamRead: true,
  canReadTournamentLink: true,
  canDeleteTournament: true,
  teamFormation: "draft"
} as const;

describe("hub tabs", () => {
  test("is the lifecycle, six entries, in the order it happens", () => {
    expect(TAB_KEYS).toEqual([
      "overview",
      "registration",
      "teams",
      "bracket",
      "matches",
      "settings"
    ]);
  });

  // Configuration used to be three tabs of its own; the gates it carried moved
  // to `allowedSettingsSection`, so only two tabs still gate themselves.
  test.each<[TabKey, boolean]>([
    ["overview", true],
    ["registration", false],
    ["teams", true],
    ["bracket", true],
    ["matches", true],
    ["settings", false]
  ])("without permissions: %s → %s", (tab, expected) => {
    expect(allowedTab(tab, NO_PERMS)).toBe(expected);
  });

  test("every tab is allowed with full permissions", () => {
    for (const tab of TAB_KEYS) {
      expect(allowedTab(tab, ALL_PERMS), tab).toBe(true);
    }
  });

  test("settings follows canUpdateTournament alone", () => {
    expect(allowedTab("settings", { ...NO_PERMS, canUpdateTournament: true })).toBe(true);
    expect(allowedTab("settings", { ...ALL_PERMS, canUpdateTournament: false })).toBe(false);
  });

  test("registration follows canTeamRead alone", () => {
    expect(allowedTab("registration", { ...NO_PERMS, canTeamRead: true })).toBe(true);
    expect(allowedTab("registration", { ...ALL_PERMS, canTeamRead: false })).toBe(false);
  });
});

describe("isTabKey", () => {
  test("accepts every declared key and nothing else", () => {
    for (const key of TAB_KEYS) {
      expect(isTabKey(key)).toBe(true);
    }
    expect(isTabKey("stages")).toBe(false);
    expect(isTabKey("pickBan")).toBe(false);
    expect(isTabKey("")).toBe(false);
  });

  test("names the segments that are routes but no longer tabs", () => {
    // The shell needs these to resolve to "no tab": treated as unknown they
    // would highlight Overview while rendering their page under it.
    for (const segment of ["logs"]) {
      expect(isLegacyTabSegment(segment), segment).toBe(true);
      expect(isTabKey(segment), segment).toBe(false);
    }
    expect(isLegacyTabSegment("bracket")).toBe(false);
    // PR-2c moved it: `/teams/draft` is a real sub-tab now, not a stray route.
    expect(isLegacyTabSegment("draft")).toBe(false);
    // PR-2e moved it: `/stages` is a 308 to `/bracket`, not a live route.
    expect(isLegacyTabSegment("stages")).toBe(false);
    // PR-2f moved them: `/pickBan` and `/links` are 308s into `/settings`.
    expect(isLegacyTabSegment("pickBan")).toBe(false);
    expect(isLegacyTabSegment("links")).toBe(false);
  });
});

describe("sub-tabs", () => {
  test("registration lands on entries", () => {
    expect(REGISTRATION_SUB_TABS[0]).toBe("entries");
    expect(REGISTRATION_SUB_TABS).toEqual(["entries", "teams", "form", "feed", "rank-autofill"]);
  });

  test("teams offers draft only when the tournament drafts", () => {
    expect(TEAMS_SUB_TABS).toEqual(["roster", "draft"]);
    expect(allowedTeamsSubTab("roster", NO_PERMS)).toBe(true);
    expect(allowedTeamsSubTab("draft", NO_PERMS)).toBe(false);
    expect(allowedTeamsSubTab("draft", ALL_PERMS)).toBe(true);
  });

  test("matches splits results into encounters and standings", () => {
    expect(MATCHES_SUB_TABS).toEqual([
      "encounters",
      "standings",
      "reports",
      "parsed",
      "logs"
    ]);
    // `report-form` is gone: it configures the report, it does not report.
    expect(MATCHES_SUB_TABS as readonly string[]).not.toContain("report-form");
  });
});

describe("settings sections", () => {
  test("carries the eleven sections in navigation order", () => {
    expect(SETTINGS_SECTIONS).toEqual([
      "general",
      "rules",
      "schedule",
      "roster",
      "pre-game",
      "report-form",
      "links",
      "challonge",
      "discord",
      "preview",
      "danger"
    ]);
  });

  // Each of these three inherits the gate of the tab it came from. Without its
  // own case it would fall into `default` and only need `tournament.update`,
  // which is a widening, not a cosmetic slip.
  test("pre-game follows canUpdateEncounter", () => {
    expect(allowedSettingsSection("pre-game", { ...ALL_PERMS, canUpdateEncounter: false })).toBe(
      false
    );
    expect(
      allowedSettingsSection("pre-game", { ...NO_PERMS, canUpdateEncounter: true })
    ).toBe(true);
  });

  test("links follows canReadTournamentLink", () => {
    expect(
      allowedSettingsSection("links", { ...ALL_PERMS, canReadTournamentLink: false })
    ).toBe(false);
    expect(allowedSettingsSection("links", { ...NO_PERMS, canReadTournamentLink: true })).toBe(
      true
    );
  });

  test("danger follows canDeleteTournament", () => {
    expect(
      allowedSettingsSection("danger", { ...ALL_PERMS, canDeleteTournament: false })
    ).toBe(false);
    expect(allowedSettingsSection("danger", { ...NO_PERMS, canDeleteTournament: true })).toBe(
      true
    );
  });

  test("every other section needs tournament.update", () => {
    const inherited: SettingsSection[] = ["pre-game", "links", "danger"];
    for (const section of SETTINGS_SECTIONS) {
      if (inherited.includes(section)) continue;
      expect(allowedSettingsSection(section, NO_PERMS), section).toBe(false);
      expect(
        allowedSettingsSection(section, { ...NO_PERMS, canUpdateTournament: true }),
        section
      ).toBe(true);
    }
  });
});
