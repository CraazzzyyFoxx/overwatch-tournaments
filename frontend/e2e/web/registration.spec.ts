import { expect, openPage, test } from "../support/fixtures";
import { battleTag, registerSelf } from "../support/flows";
import { FULL_FORM, openTournament, type AdminRegistration, type MyRegistration } from "../support/registration";
import { transitionNode, uniq } from "../support/seed";
import { selectWorkspace } from "../support/workspace";

// Registration UX after the `registration` schema split: the public CTA →
// wizard → "Pending review", the player's own card (edit / withdraw /
// check-in) and the organizer's review table. Labels are the en-US messages.

test("player registers through the wizard and lands on Pending review; the participants roster names them", async ({ adminApi, makeUser, pageAs }) => {
  const { t } = await openTournament(adminApi, { form: FULL_FORM });
  const user = await makeUser("wiz");
  const handle = battleTag(user.username);
  const page = await pageAs(user);

  await openPage(page, `/tournaments/${t.slug}`);
  await page.getByRole("button", { name: "Register", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: `Register for ${t.name}` });
  await dialog.getByRole("textbox", { name: /Battle\.net/ }).fill(handle);
  await dialog.getByRole("button", { name: "Next" }).click();
  await dialog.getByRole("radiogroup", { name: "Tank priority" }).getByRole("radio", { name: "Main" }).click();
  await dialog.getByRole("textbox", { name: /^Tank/ }).fill("3100");
  await dialog.getByRole("button", { name: "Next" }).click();
  await dialog.getByRole("button", { name: "Submit" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("link", { name: "Pending review" })).toBeVisible();

  const mine = await user.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`);
  expect(mine).toMatchObject({ status: "pending", primary_handle: handle, answers: { current_rank: { tank: 3100 } } });

  await openPage(page, `/tournaments/${t.slug}/participants`);
  await expect(page.getByText("Your Registration")).toBeVisible();
  await expect(page.getByRole("table").getByRole("link", { name: handle }), "the roster names the registrant").toBeVisible();
  await expect(page.getByRole("table").getByRole("img", { name: "Tank" }), "role glyph resolves its name").toBeVisible();
});

test("player edits only open questions, then withdraws from the participants card", async ({ adminApi, makeUser, pageAs }) => {
  const { t, version } = await openTournament(adminApi, { form: FULL_FORM });
  const user = await makeUser("card");
  await user.api.post(
    `/api/v1/tournaments/${t.id}/registration`,
    {
      form_version_id: version,
      answers: { identity_battlenet: [battleTag(user.username)], roles: [{ role: "support", is_primary: true }], current_rank: { support: 2400 } },
    },
    201
  );
  const page = await pageAs(user);
  await openPage(page, `/tournaments/${t.slug}/participants`);

  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "Edit your registration" });
  await expect(edit.getByRole("combobox", { name: /Battle\.net/ }), "the Battle.net account is frozen after submit").toBeDisabled();
  await expect(edit.getByText("Frozen after submitting")).toBeVisible();
  await edit.getByRole("button", { name: "Cancel" }).click();
  await expect(edit).toBeHidden();

  await page.getByRole("button", { name: "Withdraw", exact: true }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog", { name: "Withdraw registration?" }));
  await confirm.getByRole("button", { name: "Confirm withdraw" }).click();
  await expect.poll(async () => (await user.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`)).status).toBe("withdrawn");
  await expect(page.getByRole("button", { name: "Withdraw", exact: true })).toBeHidden();
});

test("approved player checks in from the card once CHECK_IN opens", async ({ adminApi, makeUser, pageAs }) => {
  const { t, version, registrationNodeId } = await openTournament(adminApi);
  const user = await makeUser("ci");
  const reg = await registerSelf(user, t.id, registrationNodeId, version, { roles: ["damage"] });
  await adminApi.patch(`/api/v1/admin/balancer/registrations/${reg.id}/approve`);
  await transitionNode(adminApi, registrationNodeId, "check_in");
  const page = await pageAs(user);
  await openPage(page, `/tournaments/${t.slug}/participants`);

  // An open check-in window prompts the player at once with the confirmation.
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog", { name: "Confirm check-in?" }));
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "Check-in", exact: true }).click();
  await expect(page.getByText("You have confirmed your participation!")).toBeVisible();
  expect((await user.api.get<MyRegistration>(`/api/v1/tournaments/${t.id}/registration/me`)).checked_in).toBe(true);
});

test("organizer approves from the row menu and bulk-approves the rest on Registration › Entries", async ({ adminApi, makeUser, page }) => {
  const { ws, t, version, registrationNodeId } = await openTournament(adminApi);
  const regs = [];
  for (const role of ["tank", "damage", "support"]) regs.push(await registerSelf(await makeUser("rv"), t.id, registrationNodeId, version, { roles: [role] }));
  await selectWorkspace(page.context(), ws.id);
  await openPage(page, `/admin/tournaments/${t.id}/registration/entries`);

  await page.getByRole("button", { name: `Actions for ${regs[0].primary_handle}` }).click();
  await page.getByRole("menuitem", { name: "Approve" }).click();
  await expect(page.getByText("Registration approved")).toBeVisible();

  for (const reg of regs.slice(1)) await page.getByRole("checkbox", { name: `Select row ${reg.id}` }).check();
  await page.getByRole("button", { name: "Approve 2" }).click();
  await expect(page.getByText("2 approved, 0 skipped")).toBeVisible();

  const rows = await adminApi.get<AdminRegistration[]>(`/api/v1/admin/balancer/tournaments/${t.id}/registrations`);
  expect(rows.map((r) => r.status)).toEqual(["approved", "approved", "approved"]);
});

test("organizer settings: questionnaire page, templates and custom statuses render", async ({ adminApi, page }) => {
  const { ws, t } = await openTournament(adminApi);
  await adminApi.post(`/api/v1/admin/ws/${ws.id}/balancer-statuses/custom`, { scope: "balancer", name: "Bench crew" }, 201);
  await selectWorkspace(page.context(), ws.id);

  // The legacy /registration/form link server-redirects here; under `next dev` that
  // redirect throws React's dev-only Performance.measure error, so the page is opened directly.
  await openPage(page, `/admin/tournaments/${t.id}/settings/registration`);
  await expect(page.getByText("Accepting registrations")).toBeVisible();
  await expect(page.getByText("Open", { exact: true }).first(), "the schedule window reads as open").toBeVisible();

  const name = uniq("Tpl");
  await openPage(page, "/admin/settings/registration-forms");
  await page.getByRole("textbox", { name: "New template name" }).fill(name);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect.poll(async () => (await adminApi.get<{ name: string }[]>(`/api/v1/admin/ws/${ws.id}/registration-form-templates`)).map((x) => x.name)).toContain(name);
  await expect(page.getByText(name).first()).toBeVisible();

  await openPage(page, "/admin/settings/statuses");
  await expect(page.getByText("Bench crew").first()).toBeVisible();
  await expect(page.getByText("Pending").first(), "builtin statuses are listed next to custom ones").toBeVisible();
});

// `page` carries the project's device (Pixel 7 under `mobile`); `pageAs` contexts do not.
test("@mobile registration CTA opens a usable wizard", async ({ adminApi, page }) => {
  const { t } = await openTournament(adminApi);
  await openPage(page, `/tournaments/${t.slug}`);
  await page.getByRole("button", { name: "Register", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: `Register for ${t.name}` });
  await expect(dialog.getByRole("textbox", { name: /Battle\.net/ })).toBeInViewport();
  await expect(dialog.getByRole("button", { name: "Submit" })).toBeVisible();
});
