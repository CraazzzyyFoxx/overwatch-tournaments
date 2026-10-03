// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The real copy, not `{}`: these assertions are about what a captain reads, so
// an empty message set would only ever verify missing-message fallbacks.
import messages from "@/i18n/messages/en.json";
import { MatchReportDialog } from "@/components/tournaments/MatchReportDialog";
import type {
  CaptainReport,
  Encounter,
  MatchReportForm,
  ReportBuiltInFieldConfig
} from "@/types/encounter.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getReports = vi.fn();
const getMyRole = vi.fn();
const getPickBanState = vi.fn();
const submitReport = vi.fn();

vi.mock("@/services/captain.service", () => ({
  default: {
    getReports: (...args: unknown[]) => getReports(...args),
    getMyRole: (...args: unknown[]) => getMyRole(...args),
    submitReport: (...args: unknown[]) => submitReport(...args)
  }
}));

vi.mock("@/services/pickBan.service", () => ({
  default: {
    getPickBanState: (...args: unknown[]) => getPickBanState(...args)
  }
}));

vi.mock("@/services/map.service", () => ({
  default: { getAll: () => Promise.resolve({ results: [] }) }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

function encounter(overrides: Partial<Encounter> = {}): Encounter {
  return {
    id: 42,
    created_at: new Date(0),
    updated_at: null,
    name: "A vs B",
    home_team_id: 1,
    away_team_id: 2,
    score: { home: 2, away: 1 },
    round: 1,
    best_of: 3,
    tournament_id: 7,
    stage_id: 1,
    stage_item_id: 1,
    challonge_id: null,
    status: "open",
    closeness: null,
    has_logs: false,
    result_status: "none",
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    current_map_index: null,
    confirmed_at: null,
    matches: [],
    home_team: { id: 1, name: "Alpha" } as never,
    away_team: { id: 2, name: "Bravo" } as never,
    tournament: null as never,
    stage: null,
    stage_item: null,
    ...overrides
  };
}

function field(overrides: Partial<ReportBuiltInFieldConfig> = {}): ReportBuiltInFieldConfig {
  return { enabled: true, required: false, ...overrides };
}

function form(overrides: Partial<MatchReportForm> = {}): MatchReportForm {
  return {
    tournament_id: 7,
    built_in_fields: {
      closeness: field({ required: true }),
      map_codes: field(),
      comment: field()
    },
    custom_fields: [],
    ...overrides
  };
}

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <QueryClientProvider client={client}>{node}</QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // React Query resolves through the real task queue, not just microtasks, so
  // give the four queries in this dialog several turns to commit.
  for (let turn = 0; turn < 8; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
  // Radix Dialog portals outside the container.
  return document.body;
}

async function open(reportForm: MatchReportForm, reports: CaptainReport[] = []) {
  getReports.mockResolvedValue({ reports, form: reportForm });
  return mount(<MatchReportDialog open onOpenChange={() => {}} encounter={encounter()} />);
}

function submitButton(): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button")).find(
    (button) => button.textContent?.trim() === messages.matchReport.submit
  );
}

function inputById(id: string): HTMLInputElement | HTMLTextAreaElement {
  const element = document.body.querySelector<HTMLInputElement | HTMLTextAreaElement>(`#${id}`);
  if (!element) throw new Error(`no control #${id}`);
  return element;
}

// Assigning `.value` updates React's own value tracker, so React concludes
// nothing changed and skips onChange. Write through the prototype setter.
const nativeInputValue = Object.getOwnPropertyDescriptor(
  HTMLInputElement.prototype,
  "value"
)?.set;
const nativeTextareaValue = Object.getOwnPropertyDescriptor(
  HTMLTextAreaElement.prototype,
  "value"
)?.set;

async function type(id: string, value: string) {
  const element = inputById(id);
  const setter = element instanceof HTMLTextAreaElement ? nativeTextareaValue : nativeInputValue;
  await act(async () => {
    setter?.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  getReports.mockReset();
  getMyRole.mockReset().mockResolvedValue({ side: "home" });
  getPickBanState.mockReset().mockResolvedValue(null);
  submitReport.mockReset().mockResolvedValue({ id: 1, result_status: "reported" });
});

describe("MatchReportDialog opponent report", () => {
  it("shows what the other captain wrote, including an orphaned custom answer", async () => {
    // The opposing captain's prose is the whole point of the comment channel; an
    // answer whose definition the organizer has since removed must still read,
    // falling back to its raw key rather than disappearing.
    const body = await open(
      form({
        built_in_fields: {
          closeness: field(),
          map_codes: field(),
          comment: field()
        },
        custom_fields: [
          {
            key: "vod_link",
            label: "VOD link",
            type: "text",
            required: false,
            placeholder: null
          }
        ]
      }),
      [
        {
          id: 9,
          encounter_id: 42,
          team_id: 2,
          side: "away",
          reporter_user_id: 3,
          home_score: 1,
          away_score: 2,
          closeness: null,
          map_codes: [],
          comment: "Laggy on map 2.",
          custom_fields: { vod_link: "https://x", retired_key: "orphan value" },
          created_at: null,
          updated_at: null
        }
      ]
    );

    const text = body.textContent ?? "";
    expect(text).toContain("Laggy on map 2.");
    expect(text).toContain("VOD link");
    expect(text).toContain("https://x");
    expect(text).toContain("retired_key");
    expect(text).toContain("orphan value");
    // A null rating must not surface as `null/10` or `NaN/10`.
    expect(text).not.toContain("null");
    expect(text).not.toContain("NaN");
  });
});

describe("MatchReportDialog field configuration", () => {
  it("does not render a field the tournament disabled", async () => {
    // "Disabled" has to mean absent, not merely optional: a captain must not be
    // able to file an answer the organizer switched off.
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ enabled: false }),
          comment: field()
        }
      })
    );

    expect(body.textContent).not.toContain(messages.matchReport.matchQuality);
    expect(body.textContent).not.toContain(messages.matchReport.mapCodes);
    expect(body.textContent).toContain(messages.matchReport.comment);
  });

  it("still renders the score controls when every other field is off", async () => {
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ enabled: false }),
          comment: field({ enabled: false })
        }
      })
    );

    expect(body.querySelector("#match-report-42-home-score")).not.toBeNull();
    expect(submitButton()?.disabled).toBe(false);
  });

  it("lets an optional rating stay unset instead of defaulting to a guess", async () => {
    const body = await open(
      form({
        built_in_fields: {
          closeness: field(),
          map_codes: field({ enabled: false }),
          comment: field({ enabled: false })
        }
      })
    );

    const notRated = Array.from(body.querySelectorAll('[role="radio"]')).find(
      (radio) => radio.getAttribute("aria-label") === messages.matchEdit.notSet
    );
    expect(notRated?.getAttribute("aria-checked")).toBe("true");
    expect(submitButton()?.disabled).toBe(false);

    await act(async () => {
      submitButton()?.click();
    });
    expect(submitReport.mock.calls[0][1]).toMatchObject({ closeness: null });
  });

  it("keeps the rating group to one tab stop and moves with arrow keys", async () => {
    // `role="radiogroup"` promises the APG contract: one tab stop, arrows moving
    // *and* selecting. Eleven tab stops behind that role would be worse than no
    // role at all.
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ required: true }),
          map_codes: field({ enabled: false }),
          comment: field({ enabled: false })
        }
      })
    );

    const group = body.querySelector('[role="radiogroup"]') as HTMLElement;
    const radios = Array.from(group.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
    expect(radios.length).toBe(10);
    expect(radios.filter((radio) => radio.tabIndex === 0).length).toBe(1);

    // Selected 6/10 by default (index 5); ArrowRight must move and select 7/10.
    expect(radios[5].getAttribute("aria-checked")).toBe("true");
    await act(async () => {
      radios[5].focus();
      group.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });

    const after = Array.from(group.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
    expect(after[6].getAttribute("aria-checked")).toBe("true");
    expect(after.filter((radio) => radio.tabIndex === 0)).toEqual([after[6]]);
  });
});

describe("MatchReportDialog required rules", () => {
  it("blocks submit until every played map carries a code", async () => {
    // 2-1 played three maps of a Bo3, so three codes; the reason has to be
    // readable rather than an inert grey button.
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ required: true }),
          comment: field({ enabled: false })
        }
      })
    );

    expect(body.textContent).toContain(messages.matchReport.mapCodesRequiredHint);
    expect(body.textContent).toContain(messages.matchReport.mapCodesRequiredError);
    expect(submitButton()?.disabled).toBe(true);

    await type("match-report-42-map-code-1", "AAAA1");
    await type("match-report-42-map-code-2", "BBBB2");
    expect(submitButton()?.disabled).toBe(true);

    await type("match-report-42-map-code-3", "CCCC3");
    expect(document.body.textContent).not.toContain(messages.matchReport.mapCodesRequiredError);
    expect(submitButton()?.disabled).toBe(false);
  });

  it("demands no code for a map the series never played", async () => {
    // A 1-0 forfeit of a Bo3 played one map. Demanding three would make a
    // legitimate result unreportable.
    getReports.mockResolvedValue({
      reports: [],
      form: form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ required: true }),
          comment: field({ enabled: false })
        }
      })
    });
    await mount(
      <MatchReportDialog
        open
        onOpenChange={() => {}}
        encounter={encounter({ score: { home: 1, away: 0 } })}
      />
    );

    await type("match-report-42-map-code-1", "ONLY1");
    expect(submitButton()?.disabled).toBe(false);
  });

  it("blocks submit while a required comment is blank", async () => {
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ enabled: false }),
          comment: field({ required: true })
        }
      })
    );

    expect(body.textContent).toContain(messages.matchReport.commentRequiredError);
    expect(submitButton()?.disabled).toBe(true);

    await type("match-report-42-comment", "  ");
    expect(submitButton()?.disabled).toBe(true);

    await type("match-report-42-comment", "Server crashed on map 2.");
    expect(document.body.textContent).not.toContain(messages.matchReport.commentRequiredError);
    expect(submitButton()?.disabled).toBe(false);
  });

  it("blocks submit while a required custom field is blank, naming the field", async () => {
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ enabled: false }),
          comment: field({ enabled: false })
        },
        custom_fields: [
          {
            key: "vod_link",
            label: "VOD link",
            type: "text",
            required: true,
            placeholder: "https://"
          }
        ]
      })
    );

    expect(body.textContent).toContain('"VOD link" is required');
    expect(submitButton()?.disabled).toBe(true);

    await type("match-report-42-custom-vod_link", "https://twitch.tv/x");
    expect(document.body.textContent).not.toContain('"VOD link" is required');
    expect(submitButton()?.disabled).toBe(false);
  });

  it("points the invalid control at its error text rather than colouring it", async () => {
    const body = await open(
      form({
        built_in_fields: {
          closeness: field({ enabled: false }),
          map_codes: field({ enabled: false }),
          comment: field({ required: true })
        }
      })
    );

    const textarea = inputById("match-report-42-comment");
    expect(textarea.getAttribute("aria-required")).toBe("true");
    expect(textarea.getAttribute("aria-invalid")).toBe("true");
    const describedBy = textarea.getAttribute("aria-describedby") ?? "";
    expect(describedBy).toContain("match-report-42-comment-error");
    for (const id of describedBy.split(" ")) {
      expect(body.querySelector(`#${id}`)).not.toBeNull();
    }
  });
});

describe("MatchReportDialog submission", () => {
  it("lets a captain submit a report after the result is confirmed", async () => {
    getReports.mockResolvedValue({ reports: [], form: form() });
    submitReport.mockResolvedValue({
      id: 42,
      result_status: "confirmed",
      status: "completed",
      home_score: 2,
      away_score: 1,
      closeness: 0.7,
      reports: []
    });
    let closed = false;
    await mount(
      <MatchReportDialog
        open
        onOpenChange={(open) => { closed = !open; }}
        encounter={encounter({ result_status: "confirmed", status: "completed" })}
      />
    );

    expect(submitButton()?.disabled).toBe(false);
    await type("match-report-42-comment", "Late captain report");
    await act(async () => {
      submitButton()!.click();
    });

    expect(closed).toBe(true);
  });

  it("sends the comment and custom answers, dropping the blanks", async () => {
    await open(
      form({
        built_in_fields: {
          closeness: field({ required: true }),
          map_codes: field({ enabled: false }),
          comment: field()
        },
        custom_fields: [
          { key: "vod_link", label: "VOD link", type: "text", required: false, placeholder: null },
          { key: "notes", label: "Notes", type: "text", required: false, placeholder: null }
        ]
      })
    );

    await type("match-report-42-comment", "  Close series.  ");
    await type("match-report-42-custom-vod_link", "https://twitch.tv/x");

    await act(async () => {
      submitButton()?.click();
    });

    expect(submitReport).toHaveBeenCalledWith(42, {
      home_score: 2,
      away_score: 1,
      closeness: 6,
      map_codes: [],
      comment: "Close series.",
      custom_fields: { vod_link: "https://twitch.tv/x" }
    });
  });

  it("sends a null comment when the field is enabled but left empty", async () => {
    await open(form());

    await act(async () => {
      submitButton()?.click();
    });

    expect(submitReport.mock.calls[0][1]).toMatchObject({
      comment: null,
      custom_fields: {}
    });
  });
});
