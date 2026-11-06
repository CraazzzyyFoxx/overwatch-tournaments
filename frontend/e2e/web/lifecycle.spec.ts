import type { Page } from "@playwright/test";
import { expect, openPage, test } from "../support/fixtures";
import {
  balanceAndExport,
  createStage,
  startStage,
  listEncounters,
  OW_FORM,
  openRegistration,
  rankRegistration,
  recalcStandings,
  registerSelf,
  seedBracket,
  seedPlayers,
  setResult,
} from "../support/flows";
import { createTournament, createWorkspace, nodeOf, transitionNode } from "../support/seed";

type RailItem = { label: string; locked: boolean };

/**
 * The public section rail in DOM order. An open section is a link; a locked one
 * is an aria-disabled button whose name carries the lock reason after " — ".
 */
async function readRail(page: Page): Promise<RailItem[]> {
  const nav = page.getByRole("navigation", { name: "Tournament sections" });
  await expect(nav.getByRole("link", { name: "Overview" })).toBeVisible();
  return nav.locator('a, button[aria-disabled="true"]').evaluateAll((els) =>
    els.map((el) => ({ label: (el.textContent ?? "").split(" — ")[0].trim(), locked: el.tagName === "BUTTON" }))
  );
}

// tournament-section-nav.ts: Participants second before play, last from LIVE.
const PRE_PLAY_RAIL = ["Overview", "Participants", "Teams", "Bracket", "Matches", "Statistics"];
const PLAY_RAIL = ["Overview", "Bracket", "Teams", "Matches", "Statistics", "Participants"];
const COMPETITION = ["Bracket", "Matches", "Statistics"];

async function expectRail(page: Page, labels: string[], locked: string[]) {
  await expect
    .poll(async () => readRail(page), { message: `section rail on ${page.url()}` })
    .toEqual(labels.map((label) => ({ label, locked: locked.includes(label) })));
}

test("public tournament page follows the lifecycle (anon + player)", async ({ adminApi, makeUser, pageAs, browser, pageErrors }) => {
  test.setTimeout(900_000);
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const url = `/tournaments/${t.slug}`;
  // A visitor: a context of its own, with no session.
  const anonContext = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const anon = await anonContext.newPage();
  anon.on("pageerror", (err) => pageErrors.push(`pageerror ${anon.url()}: ${err.message}`));
  const player = await makeUser("lcweb");
  const playerPage = await pageAs(player);

  await test.step("announcement: pre-play rail, competition and teams locked, no sign-up", async () => {
    await openPage(anon, url);
    await expect(anon.getByRole("heading", { level: 1 })).toContainText(t.name);
    await expectRail(anon, PRE_PLAY_RAIL, ["Teams", ...COMPETITION]);
    await expect(anon.getByRole("button", { name: "Bracket — Available when tournament play begins." })).toBeDisabled();
    await expect(anon.getByRole("button", { name: "Teams — Available once teams are formed." })).toBeDisabled();
    await expect(anon.getByRole("button", { name: /^(Register|Login to register)$/ })).toHaveCount(0);
  });

  let versionId = 0;
  let registrationNodeId = 0;
  await test.step("registration: anon is asked to log in, the player gets the Register CTA", async () => {
    ({ versionId, registrationNodeId } = await openRegistration(adminApi, t.id));
    await openPage(anon, url);
    await expect(anon.getByRole("heading", { level: 1 })).toContainText("Registration");
    await expect(anon.getByText("Login to register").first()).toBeVisible();
    await expectRail(anon, PRE_PLAY_RAIL, ["Teams", ...COMPETITION]);

    await openPage(playerPage, url);
    await expect(playerPage.getByRole("button", { name: "Register", exact: true })).toBeVisible();
  });

  await test.step("registered player sees the review state, then check-in", async () => {
    const reg = await registerSelf(player, t.id, registrationNodeId, versionId, { roles: ["support"] });
    await openPage(playerPage, url);
    // The hero CTA turns into the entry's state, linking to the participants list.
    await expect(playerPage.getByRole("link", { name: "Pending review" })).toBeVisible();
    await expect(playerPage.getByRole("button", { name: "Register", exact: true })).toHaveCount(0);

    // Organizer side: rank + approve + pool, nine more players → two balanced teams.
    await rankRegistration(adminApi, reg.id, [{ role: reg.roles[0].role, rank: 2600 }]);
    await adminApi.patch(`/api/v1/admin/balancer/registrations/${reg.id}/approve`);
    await adminApi.post(`/api/v1/admin/balancer/tournaments/${t.id}/registrations/bulk-add-to-balancer`, { registration_ids: [reg.id] });
    await seedPlayers(adminApi, t.id, 9, { registrationNodeId });
    await transitionNode(adminApi, registrationNodeId, "check_in");

    await openPage(playerPage, url);
    await expect(playerPage.getByRole("heading", { level: 1 })).toContainText("Check-in");
    // The hero names the entry's state and links to the participants page, where "Your Registration" lives.
    await playerPage.getByRole("link", { name: "Approved" }).click();
    await expect(playerPage).toHaveURL(/\/participants/);
    await expect(
      playerPage.getByText("Check-in is open — confirm your participation now."),
      "approved player is invited to check in during CHECK_IN"
    ).toBeVisible();
    await player.api.post(`/api/v1/tournaments/${t.id}/registration/me/check-in`);
    await openPage(playerPage, `${url}/participants`);
    await expect(playerPage.getByText("You have confirmed your participation!")).toBeVisible();
  });

  let teamIds: number[] = [];
  await test.step("teams exported: Teams opens before play, competition stays locked", async () => {
    // The formation starts only once its input, the registration, is closed.
    await transitionNode(adminApi, registrationNodeId, "closed");
    const formation = await nodeOf(adminApi, t.id, "formation");
    const { teams } = await balanceAndExport(adminApi, t.id, formation.id);
    teamIds = teams.map((team) => team.id);
    // tournament-service may serve teams_count 0 for ~1 s after an export: reload until the rail
    // and the Teams tab catch up, bounded so a tab that stays stale still fails.
    await openPage(anon, url);
    await expect(async () => {
      await anon.reload({ waitUntil: "domcontentloaded" });
      expect(await readRail(anon)).toEqual(PRE_PLAY_RAIL.map((label) => ({ label, locked: COMPETITION.includes(label) })));
    }, "Teams unlocks once teams are exported").toPass({ timeout: 20_000 });
    await openPage(anon, `${url}/teams`);
    await expect(async () => {
      await anon.reload({ waitUntil: "domcontentloaded" });
      for (const team of teams) await expect(anon.getByText(team.name).first()).toBeVisible({ timeout: 3_000 });
    }, "Teams tab lists every exported team").toPass({ timeout: 20_000 });
  });

  await test.step("LIVE: rail reorders, bracket opens with team names and the result", async () => {
    const stage = await createStage(adminApi, t.id, teamIds, { stageType: "single_elimination", name: "Final" });
    await startStage(adminApi, stage);

    await openPage(anon, url);
    await expect(anon.getByRole("heading", { level: 1 })).toContainText("Live");
    await expectRail(anon, PLAY_RAIL, []);

    const [match] = await listEncounters(adminApi, t.id, stage.id);
    await anon.getByRole("navigation", { name: "Tournament sections" }).getByRole("link", { name: "Bracket" }).click();
    await expect(anon).toHaveURL(new RegExp(`/tournaments/${t.slug}/bracket\\?stage=${stage.id}`));
    const card = anon.getByRole("group", { name: new RegExp(`M1: .* vs .*`) });
    for (const seat of match.teams) await expect(card).toContainText(seat.name);

    const [home, away] = [...match.teams].sort((a, b) => a.slot - b.slot);
    const scored = (name: string, score: number) => new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*${score}`);
    await setResult(adminApi, match, [2, 0]);
    await recalcStandings(adminApi, t.id);
    await openPage(anon, `${url}/bracket?stage=${stage.id}`);
    // Each seat renders "<team> <score>" (an unplayed one shows "-").
    await expect(card, "bracket card shows the home side's 2").toContainText(scored(home.name, 2));
    await expect(card, "bracket card shows the away side's 0").toContainText(scored(away.name, 0));
    await openPage(anon, `${url}/matches`);
    await expect(anon.getByText(home.name).first()).toBeVisible();
  });
  await anonContext.close();
});

test("public round-robin standings render in table order with points", async ({ page, adminApi }) => {
  const seed = await seedBracket(adminApi, { stageType: "round_robin", teams: 4 });
  const rank = (teamId: number | null) => seed.teams.findIndex((team) => team.id === teamId);
  for (const enc of seed.encounters) {
    const seats = [...enc.teams].sort((a, b) => a.slot - b.slot);
    const best = Math.min(...seats.map((s) => rank(s.team_id)));
    await setResult(adminApi, enc, seats.map((s) => (rank(s.team_id) === best ? 2 : 1)));
  }
  await recalcStandings(adminApi, seed.tournament.id);
  await openPage(page, `/tournaments/${seed.tournament.slug}`);
  const table = page.getByRole("table", { name: "Group A" });
  const rows = table.getByRole("rowgroup").nth(1).getByRole("row");
  await expect(rows).toHaveCount(4);
  for (const [i, team] of seed.teams.entries()) {
    await expect(rows.nth(i), `standings row ${i + 1}`).toContainText(team.name);
    await expect(rows.nth(i).getByRole("cell").last(), `points of ${team.name}`).toHaveText(String(3 - i));
  }
});

test("admin hub: checklist, phase strip and the header status control", async ({ page, adminApi }) => {
  test.setTimeout(600_000);
  const ws = await createWorkspace(adminApi);
  const t = await createTournament(adminApi, ws.id);
  const hub = `/admin/tournaments/${t.id}`;

  await openPage(page, hub);
  await expect(page.getByRole("heading", { level: 1, name: t.name })).toBeVisible();
  await expect(page.getByRole("list", { name: "Phases" }).getByRole("listitem")).toHaveText([
    "Announced",
    "Registration",
    "Check-in",
    "Live",
    "Playoffs",
    "Completed",
  ]);
  const checklist = page.getByRole("heading", { name: "Lifecycle checklist" }).locator("..").locator("..");
  const stateOf = (label: string) =>
    checklist.getByRole("link", { name: label }).locator("xpath=ancestor::div[contains(@class,'justify-between')][1]").getByRole("img");
  await expect(stateOf("Registration form")).toHaveAccessibleName("To do");

  // The form exists → the header's primary action opens registration (manual move).
  await adminApi.put(`/api/v1/admin/balancer/tournaments/${t.id}/registration-form`, { form_schema: OW_FORM });
  // Readiness first, so a failure below separates "API still says false" from "the checklist ignores it".
  const readiness = await adminApi.get<{ registration_form_configured: boolean }>(`/api/v1/admin/tournaments/${t.id}/readiness`);
  expect(readiness.registration_form_configured, "readiness after the form PUT").toBe(true);
  await openPage(page, hub);
  await expect(stateOf("Registration form"), "checklist reflects the saved form").toHaveAccessibleName("Done");
  await page.getByRole("button", { name: "Move to Registration" }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog"));
  await expect(confirm).toContainText("Automatic phase transitions will be turned off.");
  await confirm.getByRole("button", { name: "Set Registration" }).click();
  await expect(page.getByRole("button", { name: "Move to Check-in" })).toBeVisible();
  await expect.poll(async () => (await adminApi.get(`/api/v1/tournaments/${t.id}`)).status).toBe("registration");

  // Balancer formation has no Draft phase: from Check-in the next step is Live.
  await page.getByRole("button", { name: "Move to Check-in" }).click();
  await confirm.getByRole("button", { name: "Set Check-in" }).click();
  await expect.poll(async () => (await adminApi.get(`/api/v1/tournaments/${t.id}`)).status).toBe("check_in");
  await expect(
    page.getByRole("button", { name: "Move to Live" }),
    "check_in → next phase of a balancer tournament is Live, not Draft"
  ).toBeVisible();
  await expect(page.getByText(/Off track/)).toHaveCount(0);
});

test("public LIVE tournament page on a phone @mobile", async ({ page, adminApi }) => {
  const seed = await seedBracket(adminApi, { stageType: "single_elimination", teams: 4 });
  await openPage(page, `/tournaments/${seed.tournament.slug}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(seed.tournament.name);
  const nav = page.getByRole("navigation", { name: "Tournament sections" });
  await expect(nav.getByRole("link", { name: "Overview" })).toBeVisible();
  await nav.getByRole("link", { name: "Bracket" }).click();
  await expect(page).toHaveURL(/\/bracket/);
  const first = seed.encounters[0];
  // Phones get a round switcher + match list instead of the tree; both name the seated teams.
  const bracket = page.getByRole("tabpanel", { name: "Bracket" });
  for (const seat of first.teams) await expect(bracket).toContainText(seat.name);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page does not scroll sideways on a phone").toBeLessThanOrEqual(1);
});
