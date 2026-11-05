import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { Api, assertStatus, poll } from "../support/api";
import { AUTH_DIR, BASE_URL } from "../support/env";
import { expect, openPage, test as base } from "../support/fixtures";
import { createStage, startStage, listEncounters, openRegistration, seedTeams, setResult } from "../support/flows";
import {
  ROUTES,
  TOURNAMENT_CASES,
  TOURNAMENT_TABS,
  type PageRoute,
  type Ref,
  type SmokeData,
  type TournamentCase,
  type ViewerKind,
} from "../support/routes";
import { createTournament, createWorkspace, setStatus, uniq } from "../support/seed";
import { createUser, type TestUser } from "../support/users";

const APP_DIR = path.join(import.meta.dirname, "..", "..", "src", "app");
const WORKSPACE_COOKIE = "owt-workspace-id";
const NOT_FOUND_TITLE = "That route is off the board.";

/** Two full-roster teams in a generated single-elimination stage: one open encounter. */
async function seedBracket(api: Api, tournamentId: number) {
  const teams = await seedTeams(api, tournamentId, 2);
  const stage = await createStage(api, tournamentId, teams.map((team) => team.id), { stageType: "single_elimination" });
  await startStage(api, stage.id);
  const [encounter] = await listEncounters(api, tournamentId, stage.id);
  return { teams, encounter };
}

/** One workspace holding every entity a page route takes as a parameter. */
async function seedSmoke(api: Api, owner: TestUser): Promise<SmokeData> {
  const workspace = await createWorkspace(owner.api);
  await api.patch(`/api/v1/workspaces/${workspace.id}`, { disciplines_enabled: ["overwatch", "lol", "deadlock"] });
  // An unverified community's own page is members-only (by design); a public one is verified.
  await api.post(`/api/v1/workspaces/${workspace.id}/verification`, { verification_status: "verified" });

  const [announcement, registration, live, completed, hidden, lol, deadlock, draft] = await Promise.all([
    createTournament(api, workspace.id),
    createTournament(api, workspace.id),
    createTournament(api, workspace.id),
    createTournament(api, workspace.id),
    createTournament(api, workspace.id, { is_hidden: true }),
    createTournament(api, workspace.id, { discipline: "lol" }),
    createTournament(api, workspace.id, { discipline: "deadlock" }),
    createTournament(api, workspace.id, { team_formation: "draft" }),
  ]);
  await openRegistration(api, registration.id);

  const liveBracket = await seedBracket(api, live.id);
  await setStatus(api, live.id, "live");
  // A BattleTag-shaped name exercises the `Name#1234` ↔ `/users/Name-1234` slug round trip.
  const profile = await api.post<{ id: number; name: string }>("/api/v1/admin/users", { name: `${uniq("SmokePlayer")}#1234` });
  await api.post(
    "/api/v1/admin/players",
    {
      name: profile.name,
      team_id: liveBracket.teams[0].id,
      tournament_id: live.id,
      user_id: profile.id,
      rank: 2500,
      is_substitution: true,
    },
    201
  );

  const finished = await seedBracket(api, completed.id);
  await setStatus(api, completed.id, "live");
  await setResult(api, finished.encounter, [2, 0], "smoke seed");
  await setStatus(api, completed.id, "completed");

  await setStatus(api, draft.id, "draft");
  await api.post(`/api/v1/balancer/draft/tournaments/${draft.id}/sessions`, {});

  await api.post(`/api/v1/admin/ws/${workspace.id}/achievements/rules/seed?discipline=overwatch`);
  const rules = await api.get<{ results: { id: number }[] }>(`/api/v1/admin/ws/${workspace.id}/achievements/rules`);
  const achievements = await api.get<{ results: { id: number }[] }>("/api/v1/achievements", {
    workspace_id: workspace.id,
  });

  const ws = await api.get<{ default_division_grid_versions: Record<string, number> }>(
    `/api/v1/workspaces/${workspace.id}`
  );

  const mix = await api.post<{ id: number }>(`/api/v1/balancer/workspaces/${workspace.id}/custom-games`, {
    name: uniq("Smoke mix"),
    discipline: "overwatch",
  });

  // A scrim room needs a map pool; the catalog starts empty, so one mode + map
  // (global catalog rows, uniquely named). Created by the workspace owner: the
  // active-room cap is per caller and the platform admin is shared by every spec.
  const mode = await api.post<{ id: number }>("/api/v1/admin/catalog/overwatch/mode", {
    name: uniq("Smoke Mode"),
    slug: uniq("smoke-mode"),
  });
  const map = await api.post<{ id: number }>("/api/v1/admin/catalog/overwatch/map", {
    name: uniq("Smoke Map"),
    slug: uniq("smoke-map"),
    parent_id: mode.id,
  });
  const scrimBody = {
    workspace_id: workspace.id,
    discipline: "overwatch",
    label: uniq("Smoke scrim"),
    best_of: 1,
    team_names: ["Red", "Blue"],
    pool: {
      source: "custom",
      configs: [
        {
          kind: "map",
          item_ids: [map.id],
          ruleset: {
            version: 2,
            timer_seconds: null,
            on_timeout: "random_fill",
            phases: [{ id: "main", name: null, when: {}, pool_filter: {}, generator: "bracket", steps: [] }],
          },
        },
      ],
    },
  };
  // ponytail: the creator's new owner role reaches the workers only after the
  // principal cache expires (~30-60 s, reported as a finding); retry the 403 meanwhile.
  const scrim = await poll(async () => {
    const res = await owner.api.raw("POST", "/api/v1/scrims", { body: scrimBody });
    if (res.status() === 403) return null;
    await assertStatus(res, "POST", "/api/v1/scrims", 201);
    return (await res.json()) as { token: string };
  }, "scrim room as the workspace owner", 120_000);

  const tournaments: Record<TournamentCase, Ref> = { announcement, registration, live, completed, hidden, lol, deadlock };
  return {
    workspace: { id: workspace.id, slug: workspace.slug },
    tournaments: Object.fromEntries(
      Object.entries(tournaments).map(([key, t]) => [key, { id: t.id, slug: t.slug }])
    ) as Record<TournamentCase, Ref>,
    draft: { id: draft.id, slug: draft.slug },
    teamId: liveBracket.teams[0].id,
    encounterId: liveBracket.encounter.id,
    player: { id: profile.id, slug: profile.name.replace("#", "-") },
    achievementId: achievements.results[0].id,
    achievementRuleId: rules.results[0].id,
    divisionVersionId: ws.default_division_grid_versions.overwatch,
    mixId: mix.id,
    scrimToken: scrim.token,
  };
}

type Viewer = Pick<TestUser, "accessToken" | "refreshToken">;

const test = base.extend<object, { smoke: SmokeData; viewer: Viewer }>({
  smoke: [
    async ({ admin }, use) => {
      // Playwright restarts the worker after each failed test; seed once per
      // run (workers are children of the runner), not once per worker start.
      const file = path.join(AUTH_DIR, `smoke-${process.ppid}.json`);
      if (!fs.existsSync(file)) {
        const api = await Api.create(admin.accessToken);
        const owner = await createUser({ prefix: "smokeown" });
        fs.writeFileSync(file, JSON.stringify(await seedSmoke(api, owner)));
        await Promise.all([api.dispose(), owner.api.dispose()]);
      }
      await use(JSON.parse(fs.readFileSync(file, "utf8")) as SmokeData);
    },
    { scope: "worker", timeout: 300_000 },
  ],
  // A signed-in user with no workspace role: the public site works, the admin zone refuses.
  viewer: [
    async ({}, use) => {
      const { api, ...user } = await createUser({ prefix: "smokeview" });
      await api.dispose();
      await use(user);
    },
    { scope: "worker" },
  ],
});

/**
 * The page rendered its own content: no 404, no failed-section card, its
 * content root visible with a heading — or, for an empty/locked section, the
 * page-state card that stands in for it (a <p> title, no heading; reported).
 * `root` defaults to the site's <main>.
 */
async function expectContent(page: Page, url: string, root = page.getByRole("main"), heading = true) {
  await expect(page.getByText(NOT_FOUND_TITLE), `${url}: unexpected not-found page`).toHaveCount(0);
  await expect(root.first(), `${url}: content landmark`).toBeVisible();
  if (heading) {
    const stateCard = root.getByRole("status").filter({ visible: true, hasText: /\S/, hasNotText: /Loading/i });
    await expect(root.getByRole("heading").or(stateCard).first(), `${url}: page heading`).toBeVisible();
  }
  // A PageStateCard in its `error` state (<section role=alert>) is a section whose read failed. Not every
  // role=alert: Next's route announcer and domain warnings (draft "Blocking issues") use it legitimately.
  await expect(page.locator("section[role=alert]").filter({ visible: true }), `${url}: error state rendered`).toHaveCount(0);
}

async function expectNotFound(page: Page, url: string) {
  await expect(page.getByText(NOT_FOUND_TITLE), `${url}: not-found page`).toBeVisible();
}

async function expectDenied(page: Page, url: string) {
  await expect(page, `${url}: denial keeps the URL`).toHaveURL(new URL(url, BASE_URL).href);
  await expect(page.getByText(/^(No access|Unauthorized)$/), `${url}: denial screen`).toBeVisible();
}

async function useWorkspace(page: Page, workspaceId: number) {
  await page.context().addCookies([{ name: WORKSPACE_COOKIE, value: String(workspaceId), url: BASE_URL }]);
}

/** Failed reads that ARE the expected outcome: a refused zone read on a denial screen, the 404 behind a not-found page. */
const REFUSED = /Failed to load resource: the server responded with a status of 40[134]/;

async function visit(page: Page, route: PageRoute, smoke: SmokeData, viewer: ViewerKind, errors: string[]) {
  const url = route.url(smoke);
  await openPage(page, url);
  const notFound = route.notFoundFor?.includes(viewer) ?? false;
  const denied = route.access === "admin" && viewer !== "admin";
  if (notFound || denied) {
    await (notFound ? expectNotFound(page, url) : expectDenied(page, url));
    errors.splice(0, errors.length, ...errors.filter((error) => !REFUSED.test(error)));
    return;
  }
  await expectContent(page, url);
}

test("route inventory covers every page.tsx", () => {
  const onDisk = (fs.readdirSync(APP_DIR, { recursive: true }) as string[])
    .map((file) => file.split(path.sep).join("/"))
    .filter((file) => file === "page.tsx" || file.endsWith("/page.tsx"))
    .sort();
  const listed = ROUTES.map((route) => route.file).sort();
  expect(listed, "support/routes.ts lists a page twice").toEqual([...new Set(listed)]);
  expect(listed, "support/routes.ts must list exactly the page.tsx files under src/app").toEqual(onDisk);
});

for (const route of ROUTES) {
  test.describe(route.file, () => {
    test("platform admin", async ({ page, smoke, pageErrors }) => {
      await useWorkspace(page, smoke.workspace.id);
      await visit(page, route, smoke, "admin", pageErrors);
    });

    test("signed-in user without a role", async ({ pageAs, smoke, viewer, pageErrors }) => {
      await visit(await pageAs(viewer), route, smoke, "user", pageErrors);
    });

    if (route.access === "public") {
      test("anonymous", async ({ page, smoke, pageErrors }) => {
        await page.context().clearCookies();
        await visit(page, route, smoke, "anon", pageErrors);
      });
    }
  });
}

test("anonymous visitor of the admin zone is sent to sign-in", async ({ page, smoke }) => {
  await page.context().clearCookies();
  for (const url of ["/admin", `/admin/tournaments/${smoke.tournaments.live.id}/overview`]) {
    await page.goto(url);
    await expect(page, `${url}: sign-in redirect`).toHaveURL(
      (current) => current.pathname === "/" && current.searchParams.get("login") === "1" && current.searchParams.get("next") === url
    );
    await expect(page.getByRole("dialog"), `${url}: sign-in dialog`).toBeVisible();
  }
});

// Public tabs per lifecycle status: locked tabs (bracket/matches/stats before
// LIVE, content-less rules/maps/stream) must redirect or show a locked state, never crash.
for (const status of TOURNAMENT_CASES) {
  test.describe(`public tournament tabs: ${status}`, () => {
    for (const tab of TOURNAMENT_TABS) {
      test(`/${tab || "overview"} anonymous`, async ({ page, smoke, pageErrors }) => {
        await page.context().clearCookies();
        const slug = smoke.tournaments[status].slug;
        const url = `/tournaments/${slug}${tab ? `/${tab}` : ""}`;
        await openPage(page, url);
        if (status === "hidden") {
          await expectNotFound(page, url);
          pageErrors.splice(0, pageErrors.length, ...pageErrors.filter((error) => !REFUSED.test(error)));
          return;
        }
        await expect(page, `${url}: stays on the tournament`).toHaveURL(new RegExp(`/tournaments/${slug}`));
        await expectContent(page, url);
      });
    }
  });
}

test("hidden tournament is visible to the platform admin", async ({ page, smoke }) => {
  const url = `/tournaments/${smoke.tournaments.hidden.slug}`;
  await openPage(page, url);
  await expectContent(page, url);
});
