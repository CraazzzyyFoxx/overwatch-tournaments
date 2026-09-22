// @vitest-environment happy-dom
//
// Check-in is the only deadline a player can miss on this page, and the card
// that carries it sits above a virtualised roster: on a phone it is one swipe
// of "Your Registration" among a hundred rows. Two things are pinned here:
//
//  1. the first visit while the check-in window is open opens the confirm
//     dialog by itself, so nobody has to notice a button to learn check-in is
//     live — and it does that ONCE per tournament per browser, because a modal
//     that returns on every reload only teaches the dismiss reflex;
//  2. the button stays the way back in afterwards, and neither the button nor
//     the prompt exists when there is nothing to confirm (already checked in,
//     or the window is not open).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type {
  Registration,
  RegistrationForm,
  RegistrationListResponse
} from "@/types/registration.types";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentParticipantsPage from "./TournamentParticipantsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 88;

const getMyRegistration = vi.fn();
const listRegistrations = vi.fn();
const getForm = vi.fn();
const checkInMyRegistration = vi.fn();
const withdrawMyRegistration = vi.fn();
const updateMyRegistration = vi.fn();

vi.mock("@/services/registration.service", () => ({
  default: {
    getMyRegistration: (...args: unknown[]) => getMyRegistration(...args),
    listRegistrations: (...args: unknown[]) => listRegistrations(...args),
    getForm: (...args: unknown[]) => getForm(...args),
    checkInMyRegistration: (...args: unknown[]) => checkInMyRegistration(...args),
    withdrawMyRegistration: (...args: unknown[]) => withdrawMyRegistration(...args),
    updateMyRegistration: (...args: unknown[]) => updateMyRegistration(...args),
    getMySubscriptionStatus: () => Promise.resolve({ required: false, verdicts: {} })
  }
}));

// The `top_heroes` column is visible by default, so the hero catalogue is
// fetched on mount. It backs nothing this test asserts.
vi.mock("@/services/hero.service", () => ({
  default: { getAll: () => Promise.resolve({ results: [] }) }
}));

// Pulled in by the self-edit dialog, for the identity questions' suggestions.
vi.mock("@/services/me.service", () => ({
  default: { getSocialAccounts: () => Promise.resolve(null) }
}));
vi.mock("@/services/rbac.service", () => ({
  rbacService: { listOAuthConnections: () => Promise.resolve({ results: [] }) }
}));

// Signed in, because an anonymous visitor has no registration to check in.
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({
    status: "authenticated",
    user: { id: 5 },
    error: null,
    refetch: () => {}
  })
}));

/**
 * The roster itself: virtualised, ResizeObserver-driven, and irrelevant to the
 * card above it. Its own behaviour test covers it.
 */
vi.mock("./_components/VirtualParticipantsList", () => ({
  default: () => <div data-testid="roster" />
}));

vi.mock("next/navigation", () => ({
  usePathname: () => `/tournaments/${TOURNAMENT_ID}/participants`,
  useSearchParams: () => new URLSearchParams(),
  // `ViewSegment` writes `?view=` through `useQueryParams`, which needs a router.
  useRouter: () => ({ push: () => {}, replace: () => {} })
}));

let tournament: Tournament;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: tournament, isError: false, refetch: () => {} })
}));

/**
 * Every field spelled out rather than cast: `tsconfig.json` excludes test
 * files, so a fixture that lies about its shape type-checks green.
 */
function makeTournament(status: TournamentStatus, window: { starts_at: string; ends_at: string | null }): Tournament {
  return {
    id: TOURNAMENT_ID,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 3,
    name: "Anak Cup",
    start_date: new Date(0),
    end_date: new Date(0),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: "balancer",
    status,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    phase_schedule: [{ status: "check_in", ...window }],
    win_points: 1,
    draw_points: 0.5,
    loss_points: 0,
    stages: [],
    participants_count: 1,
    registrations_count: 1,
    teams_count: null,
    division_grid_version_id: null,
    division_grid_version: null,
    roster_slots_json: null,
    roster_shape: null,
    roster_locked_by_draft: null
  };
}

function makeRegistration(overrides: Partial<Registration> = {}): Registration {
  return {
    id: 401,
    tournament_id: TOURNAMENT_ID,
    workspace_id: 3,
    user_id: 5,
    battle_tag: "Anak#2100",
    roles: [{ role: "damage", subrole: null, is_primary: true, priority: 0, top_heroes: [] }],
    answers: { stream_pov: false },
    form_version_id: 4,
    form_version_stale: false,
    status: "approved",
    checked_in: false,
    profiles_open: null,
    // Required on every registration read. Two switched-off requirements is the
    // shape `FORM` below describes, and the progress chain must skip both.
    admission: {
      decision: "pending_check_in",
      requirements: [
        { key: "open_profile", state: "not_applicable", stage: "check_in", reasons: [], detail: {} },
        { key: "subscription", state: "not_applicable", stage: "check_in", reasons: [], detail: {} }
      ],
      blockers: [],
      overridden: [],
      checked_in: false,
      ready: true
    },
    submitted_at: null,
    reviewed_at: null,
    submitted_late: false,
    // The server's self-edit verdict. Closed by default, exactly as a
    // tournament whose organizer never opened a question reads.
    can_edit: false,
    edit_locked_reason: "nothing_editable",
    edit_writable_keys: [],
    ...overrides
  };
}

/**
 * The list envelope the server returns. `hidden`/`total`/`role_counts` are ITS
 * answer: a tournament whose organizer hid the roster sends the aggregate and
 * NO rows, which is why the page cannot count anything itself.
 */
function regList(
  registrations: Registration[],
  overrides: Partial<RegistrationListResponse> = {}
): RegistrationListResponse {
  return {
    registrations,
    division_grids: {},
    hidden: false,
    total: registrations.length,
    role_counts: {},
    max_participants: null,
    ...overrides
  };
}

const FORM: RegistrationForm = {
  id: 9,
  tournament_id: TOURNAMENT_ID,
  workspace_id: 3,
  is_open: false,
  require_open_profile: false,
  require_subscription: false,
  form_schema: {
    schema_version: 1,
    sections: [
      {
        key: "accounts",
        fields: [
          {
            key: "battle_tag",
            kind: "builtin",
            required: true,
            visibility: "public",
            params: {},
          },
          {
            key: "stream_pov",
            kind: "builtin",
            required: false,
            visibility: "public",
            params: {},
          },
          {
            key: "scrims",
            kind: "checkbox",
            label: "Ready for scrims?",
            required: false,
            visibility: "public",
            params: {},
          },
          // Organizers-only: a public read never carries its answer, so the
          // card must not build a row for it.
          {
            key: "organizer_notes",
            kind: "textarea",
            label: "For the organizers",
            required: false,
            visibility: "organizers",
            params: {},
          }
        ]
      }
    ]
  },
  version_id: 4,
  version_number: 1
};

/** An hour either side of now, i.e. the window is open. */
const OPEN_WINDOW = {
  starts_at: new Date(Date.now() - 3_600_000).toISOString(),
  ends_at: new Date(Date.now() + 3_600_000).toISOString()
};
/** Both bounds in the past: the phase is still `check_in`, the window is not. */
const CLOSED_WINDOW = {
  starts_at: new Date(Date.now() - 7_200_000).toISOString(),
  ends_at: new Date(Date.now() - 3_600_000).toISOString()
};

let container: HTMLDivElement;
let root: Root;

// Node 22 exposes its own `localStorage` that throws without
// `--localstorage-file`, and happy-dom does not shadow it. A per-test in-memory
// store is also what "the same browser, one reload later" means here: the store
// survives a remount inside a test and never leaks into the next one.
beforeEach(() => {
  vi.clearAllMocks();
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      get length() {
        return stored.size;
      },
      key: (index: number) => Array.from(stored.keys())[index] ?? null,
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, String(value)),
      removeItem: (key: string) => void stored.delete(key),
      clear: () => stored.clear()
    }
  });
  tournament = makeTournament("check_in", OPEN_WINDOW);
  listRegistrations.mockResolvedValue(regList([makeRegistration()]));
  getForm.mockResolvedValue(FORM);
  getMyRegistration.mockResolvedValue(makeRegistration());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentParticipantsPage slug={String(TOURNAMENT_ID)} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Radix portals the dialog to `document.body`, outside the render container. */
function dialog(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[role="alertdialog"][data-state="open"]');
}

/** The card's own check-in button, not the dialog's confirm action. */
function checkInButton(): HTMLButtonElement | null {
  return (
    Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === en.common.checkIn
    ) ?? null
  );
}

describe("tournament participants check-in", () => {
  it("opens the check-in dialog on the first visit while the window is open", async () => {
    await mount();

    expect(dialog()?.textContent).toContain(en.common.confirmCheckIn);
    // The button is the way back in once the dialog is dismissed, so it must
    // render alongside the prompt rather than instead of it.
    expect(checkInButton()).not.toBeNull();
  });

  it("prompts once per tournament, and never for another tournament's deadline", async () => {
    await mount();
    expect(dialog()).not.toBeNull();

    // A reload: same browser, same tournament, nothing confirmed yet.
    await act(async () => root.unmount());
    root = createRoot(container);
    await mount();
    expect(dialog()).toBeNull();
    // Still reachable by hand — the one-shot suppresses the prompt, not the action.
    await act(async () => {
      checkInButton()?.click();
    });
    expect(dialog()?.textContent).toContain(en.common.confirmCheckIn);

    // A different tournament is a different deadline and prompts on its own.
    await act(async () => root.unmount());
    root = createRoot(container);
    tournament = { ...makeTournament("check_in", OPEN_WINDOW), id: TOURNAMENT_ID + 1 };
    await mount();
    expect(dialog()).not.toBeNull();
  });

  it("stays quiet when there is nothing to confirm", async () => {
    getMyRegistration.mockResolvedValue(makeRegistration({ checked_in: true }));
    await mount();
    expect(dialog()).toBeNull();
    expect(checkInButton()).toBeNull();

    await act(async () => root.unmount());
    root = createRoot(container);
    window.localStorage.clear();
    getMyRegistration.mockResolvedValue(makeRegistration());
    tournament = makeTournament("check_in", CLOSED_WINDOW);
    await mount();
    expect(dialog()).toBeNull();
    expect(checkInButton()).toBeNull();
  });
});

/**
 * The registrant's progress chain used to be two hand-written blocks behind two
 * `require_*` flags, each re-deriving the admission rule from a raw signal. It is
 * now one walk over `admission.requirements`, and the properties that walk MUST
 * preserve are the ones a wrong tone gets wrong loudest: a player told they are
 * out when a provider is merely down, and a player told they are out after an
 * organizer already let them in.
 */
function stepLabels(): { text: string; className: string }[] {
  return Array.from(container.querySelectorAll("span"))
    .filter((node) => node.className.includes("text-label leading-tight"))
    .map((node) => ({ text: node.textContent ?? "", className: node.className }));
}

function step(text: string): { text: string; className: string } {
  const found = stepLabels().find((candidate) => candidate.text === text);
  if (!found) {
    throw new Error(`No step labelled "${text}" among ${JSON.stringify(stepLabels())}`);
  }
  return found;
}

const requirement = (
  overrides: Partial<Registration["admission"]["requirements"][number]>
): Registration["admission"]["requirements"][number] => ({
  key: "subscription",
  state: "undetermined",
  stage: "check_in",
  reasons: [],
  detail: {},
  ...overrides
});

describe("registration progress steps", () => {
  it("draws one step per active requirement and skips the switched-off ones", async () => {
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        admission: {
          decision: "pending_check_in",
          requirements: [
            requirement({ key: "open_profile", state: "satisfied" }),
            requirement({ key: "subscription", state: "not_applicable" })
          ],
          blockers: [],
          overridden: [],
          checked_in: false,
          ready: true
        }
      })
    );
    await mount();

    // Satisfied requirements are named, not explained: a passing verdict can
    // still carry reasons (subscription `any` mode) and rendering one would
    // caption a green step with a complaint.
    expect(step(en.admission.requirement.open_profile).className).toContain("aqt-emerald");
    expect(stepLabels().map((candidate) => candidate.text)).not.toContain(
      en.admission.requirement.subscription
    );
  });

  it("draws an undetermined requirement as still-running, never as a failure", async () => {
    // Fail-open. A Discord outage during check-in must not tell a paying
    // subscriber they are out.
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        admission: {
          decision: "pending_check_in",
          requirements: [
            requirement({
              reasons: [{ code: "provider_unavailable", actor: "system", subject: "discord" }]
            })
          ],
          blockers: [],
          overridden: [],
          checked_in: false,
          ready: true
        }
      })
    );
    await mount();

    const pending = step(`${en.admission.reason.provider_unavailable} (discord)`);
    expect(pending.className).toContain("aqt-amber");
    expect(pending.className).not.toContain("aqt-rose");
    // A system reason is not the player's to fix, so it gets no call to action.
    expect(pending.className).not.toContain("underline");
  });

  it("marks a blocked requirement as failed and hands the player the action", async () => {
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        admission: {
          decision: "not_admitted",
          requirements: [
            requirement({
              key: "open_profile",
              state: "blocked",
              reasons: [{ code: "profile_private", actor: "player", subject: "Anak#2100" }]
            })
          ],
          blockers: [],
          overridden: [],
          checked_in: false,
          ready: true
        }
      })
    );
    await mount();

    const failed = step(`${en.admission.reason.profile_private} (Anak#2100)`);
    expect(failed.className).toContain("aqt-rose");
    expect(failed.className).toContain("underline");
  });

  it("leaves an overridden requirement out of the failures once check-in is behind it", async () => {
    // D2/D4: check-in is the last gate of every requirement. The step stays
    // visible with its reason, but the player is admitted and the chain must not
    // read as a refusal.
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        checked_in: true,
        admission: {
          decision: "admitted",
          requirements: [requirement({ key: "open_profile", state: "satisfied" })],
          blockers: [],
          overridden: [],
          checked_in: true,
          ready: true
        }
      })
    );
    await mount();

    expect(
      stepLabels().filter((candidate) => candidate.className.includes("aqt-rose"))
    ).toHaveLength(0);
  });
});

describe("a roster the organizer hid", () => {
  /** The server's answer when `hide_registrations` is on: aggregate, no rows. */
  const HIDDEN = regList([], {
    hidden: true,
    total: 48,
    role_counts: { tank: 8, damage: 24, support: 16 },
    max_participants: 60
  });

  it("shows the count and the role split instead of the roster", async () => {
    listRegistrations.mockResolvedValue(HIDDEN);
    await mount();

    const summary = container.querySelector(
      `section[aria-label="${en.tournamentDetail.participants.hidden.title}"]`
    );
    expect(summary).not.toBeNull();
    const text = summary?.textContent ?? "";
    expect(text).toContain("48");
    // Advisory capacity, rendered beside the count and never compared to it.
    expect(text).toContain("/ 60");
    expect(text).toContain(en.common.roles.tank);
    expect(text).toContain("24");
  });

  it("drops the filters and the empty state rather than claiming nobody registered", async () => {
    listRegistrations.mockResolvedValue(HIDDEN);
    await mount();

    // No rows is not "no registrations": the roster exists, it is just not published.
    expect(container.textContent).not.toContain(en.tournamentDetail.participants.empty.title);
    expect(container.querySelector(".filters")).toBeNull();
  });

  it("still renders the viewer's own card, with its place overall and on its role", async () => {
    listRegistrations.mockResolvedValue(HIDDEN);
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        queue_position: 12,
        queue_total: 48,
        queue_role: "damage",
        queue_role_position: 4,
        queue_role_total: 24
      })
    );
    await mount();

    const chip = (label: string) => container.querySelector(`[aria-label="${label}"]`);
    const overall = chip(
      en.registration.myCard.queuePositionLabel.replace("{position}", "12").replace("{total}", "48")
    );
    expect(overall?.textContent).toBe("12 / 48");

    // The place that decides whether they get in — 12th of 48 says little next
    // to the 24 other DPS competing for the same slots.
    const onRole = chip(
      en.registration.myCard.queueRolePositionLabel
        .replace("{position}", "4")
        .replace("{total}", "24")
        .replace("{role}", en.common.roles.damage)
    );
    expect(onRole?.textContent).toBe(`${en.common.roles.damage} 4 / 24`);
  });

  it("shows the handles, notes and every asked answer, and nothing the form did not ask", async () => {
    // The card reads the flat `answers` document against the form's PUBLIC
    // questions. An answer that is absent was either never asked or is not
    // this reader's to see; a question the reader never answered is still a
    // row, because the roster's own details panel shows it that way too.
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        answers: {
          identity_discord: "anak",
          identity_youtube: "@anak",
          public_notes: "I can play late",
          stream_pov: true,
          scrims: false
        }
      })
    );
    await mount();

    const expand = container.querySelector<HTMLButtonElement>(
      `[aria-label="${en.registration.myCard.showDetails}"]`
    );
    await act(async () => expand?.click());
    const card = container.textContent ?? "";

    expect(card).toContain("anak");
    expect(card).toContain("@anak");
    // No brand icon for YouTube, so the chip is labelled with the provider.
    expect(card).toContain(en.registration.accounts.youtube);
    expect(card).toContain("I can play late");
    // Twitch was not answered and Boosty was not asked: neither gets a chip.
    expect(card).not.toContain(en.registration.accounts.twitch);
    expect(card).not.toContain(en.registration.accounts.boosty);

    // The toggles read as Yes/No rows, the same way as any other question —
    // no bespoke "will stream" chip — and the organizers-only question is
    // absent rather than blank.
    const rows = Array.from(container.querySelectorAll("dl dt")).map((dt) => [
      dt.textContent,
      dt.nextElementSibling?.textContent
    ]);
    expect(rows).toContainEqual([en.registration.details.streamPov, en.common.yes]);
    expect(rows).toContainEqual(["Ready for scrims?", en.common.no]);
    expect(card).not.toContain("For the organizers");
  });

  it("says nothing about a role queue for a registration that declared no role", async () => {
    // The server sends the role numbers as absent, not as zero: "0 of 0" and
    // "1 of 1" are both places nobody holds.
    listRegistrations.mockResolvedValue(HIDDEN);
    getMyRegistration.mockResolvedValue(
      makeRegistration({ roles: [], queue_position: 12, queue_total: 48 })
    );
    await mount();

    expect(
      container.querySelector('[aria-label^="Position 4 of"]')
    ).toBeNull();
    expect(container.textContent).toContain("12 / 48");
  });
});

/** The card's Edit action, found by the marker rather than by its label: the
 *  label is localized and this file mounts the real message catalogue. */
function editButton(): HTMLButtonElement | null {
  return container.querySelector<HTMLButtonElement>("[data-registration-edit]");
}

describe("editing your own registration", () => {
  it("hides the action while the form has nothing open", async () => {
    // Closed by default: every tournament whose organizer never ticked
    // `editable` on a question reports `nothing_editable`, and a permanently
    // dead button on every card is worse than no button.
    await mount();
    expect(editButton()).toBeNull();
  });

  it("offers the action exactly when the server says the row is editable", async () => {
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        can_edit: true,
        edit_locked_reason: null,
        edit_writable_keys: ["public_notes"]
      })
    );
    await mount();

    const button = editButton();
    expect(button).not.toBeNull();
    expect(button?.disabled).toBe(false);
  });

  it("keeps the action visible but dead, with the reason, once something closed it", async () => {
    // A registrant who could edit yesterday and cannot today is owed the
    // reason. `checked_in` froze the entry the organizer is about to balance.
    getMyRegistration.mockResolvedValue(
      makeRegistration({
        checked_in: true,
        can_edit: false,
        edit_locked_reason: "checked_in",
        edit_writable_keys: []
      })
    );
    await mount();

    const button = editButton();
    expect(button?.disabled).toBe(true);
    // The tooltip carries the REASON, not a second copy of the action label.
    expect(button?.title).not.toBe("");
    expect(button?.title).not.toBe(button?.textContent?.trim());
  });

  it("waits for the form before offering an edit of it", async () => {
    // The dialog renders the form's schema and echoes its version id back, so
    // `can_edit` alone is not enough to act on.
    getForm.mockResolvedValue(null);
    getMyRegistration.mockResolvedValue(
      makeRegistration({ can_edit: true, edit_locked_reason: null, edit_writable_keys: ["roles"] })
    );
    await mount();

    expect(editButton()).toBeNull();
  });

  it("saves only the allowlisted answers and refreshes the card from the response", async () => {
    // Re-sending an unchanged answer for a frozen key is still a write of it,
    // and the server refuses the whole request with `code: "locked"` — so the
    // dialog must send the allowlist and nothing else.
    getForm.mockResolvedValue({
      ...FORM,
      form_schema: {
        schema_version: 1,
        sections: [
          {
            key: "details",
            fields: [
              {
                key: "battle_tag",
                kind: "builtin",
                required: true,
                visibility: "public",
                params: {},
              },
              {
                key: "public_notes",
                kind: "builtin",
                required: false,
                visibility: "public",
                params: {},
              }
            ]
          }
        ]
      }
    });
    const editable = {
      can_edit: true,
      edit_locked_reason: null,
      edit_writable_keys: ["public_notes"]
    };
    getMyRegistration.mockResolvedValue(
      makeRegistration({ ...editable, answers: { public_notes: "before" } })
    );
    updateMyRegistration.mockResolvedValue(
      makeRegistration({ ...editable, answers: { public_notes: "before", reserve: true } })
    );
    await mount();

    await act(async () => editButton()?.click());
    const modal = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(modal).not.toBeNull();

    const submit = Array.from(modal?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent?.trim() === en.common.submit
    );
    await act(async () => submit?.click());
    await settle();

    expect(updateMyRegistration).toHaveBeenCalledWith(TOURNAMENT_ID, {
      form_version_id: FORM.version_id,
      answers: { public_notes: "before" }
    });
    // The response IS the updated row, so the card behind the dialog re-reads
    // it without a second round trip — here, as a reserve.
    expect(container.querySelector("[data-registration-reserve]")).not.toBeNull();
  });
});

describe("on-call players", () => {
  const ON_CALL = makeRegistration({
    id: 402,
    user_id: 9,
    battle_tag: "Sub#1000",
    answers: { reserve: true }
  });

  it("leaves them in the one list and says nothing about how many there are", async () => {
    listRegistrations.mockResolvedValue(regList([makeRegistration(), ON_CALL], { total: 2 }));
    await mount();

    // The answer is availability, not membership: ONE list, no second one with
    // its own header. And the roster does not publish a tally of who offered --
    // that is organizer bookkeeping, readable through the opt-in column.
    expect(container.querySelectorAll('[data-testid="roster"]').length).toBe(1);
    expect(container.querySelector("[data-reserve-group]")).toBeNull();
    expect(container.querySelector("[data-reserve-count]")).toBeNull();
  });

  it("marks the owner's own card and explains what they agreed to", async () => {
    getMyRegistration.mockResolvedValue(makeRegistration({ answers: { reserve: true } }));
    await mount();

    expect(container.querySelector("[data-registration-reserve]")).not.toBeNull();
    expect(container.textContent).toContain(en.registration.reserve.explainer);
  });
});

describe("late sign-ups", () => {
  it("marks a row the server flagged as late", async () => {
    getMyRegistration.mockResolvedValue(makeRegistration({ submitted_late: true }));
    await mount();

    expect(container.querySelector("[data-registration-late]")).not.toBeNull();
  });

  it("says nothing for an on-time sign-up", async () => {
    await mount();
    expect(container.querySelector("[data-registration-late]")).toBeNull();
  });
});
