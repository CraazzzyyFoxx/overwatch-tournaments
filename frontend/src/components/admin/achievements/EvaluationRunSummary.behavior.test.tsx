// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationRunSummary } from "@/components/admin/achievements/EvaluationRunSummary";
import type { EvaluationRunRead } from "@/types/admin.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ number: (value: number) => String(value) })
}));

vi.mock("@/lib/notify", () => ({
  notify: {
    message: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn()
  }
}));

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(node);
  });
  return container;
}

function click(element: Element) {
  return act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

const GRID_CAUSE = "Missing division grid mappings to normalized base version 19: [20]";

const SKIPPED = [
  "my-strength-is-growing",
  "not-good-enough",
  "i-need-more-power",
  "balance-from-anak",
  "critical-failure",
  "im-fine-with-that",
  "damage-above-5-division",
  "tank-above-5-division",
  "support-above-5-division"
];

function run(overrides: Partial<EvaluationRunRead> = {}): EvaluationRunRead {
  return {
    id: "3f1d",
    workspace_id: 1,
    trigger: "manual",
    tournament_id: null,
    rules_evaluated: 116,
    results_created: 1149,
    results_removed: 11,
    started_at: "2026-09-16T10:00:00Z",
    finished_at: "2026-09-16T10:00:12Z",
    status: "partial",
    error_message: null,
    ...overrides
  };
}

/** The grouped shape the runner writes: one entry per reason, slugs comma-joined. */
const groupedMessage = `${SKIPPED.join(", ")}: ${GRID_CAUSE}`;

/** The pre-grouping shape still stored on older runs: one entry per rule. */
const repeatedMessage = SKIPPED.map((slug) => `${slug}: ${GRID_CAUSE}`).join("; ");

describe("EvaluationRunSummary", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it.each([
    ["grouped", groupedMessage],
    ["one entry per rule", repeatedMessage]
  ])("states a shared cause once, whatever the stored shape (%s)", async (_shape, message) => {
    // Nine rules blocked by one missing mapping printed the same sentence nine
    // times, so the single thing to fix was buried under its own repetitions.
    const scope = await mount(
      <EvaluationRunSummary run={run({ error_message: message })} onDismiss={() => {}} />
    );

    expect(scope.textContent?.split(GRID_CAUSE)).toHaveLength(2);
    expect(scope.textContent).toContain("9 of 125 rules could not run");
  });

  it("keeps every skipped rule reachable behind one disclosure", async () => {
    // A cause can block dozens of rules; the list must not push the counts and
    // the reason off the screen, and must not lose a slug either.
    const scope = await mount(
      <EvaluationRunSummary run={run({ error_message: groupedMessage })} onDismiss={() => {}} />
    );

    expect(scope.textContent).toContain("my-strength-is-growing");
    expect(scope.textContent).not.toContain("support-above-5-division");

    const disclosure = scope.querySelector("button[aria-expanded]");
    expect(disclosure?.textContent).toContain("Show 1 more");

    await click(disclosure!);
    expect(scope.textContent).toContain("support-above-5-division");
    expect(scope.querySelector("button[aria-expanded]")?.getAttribute("aria-expanded")).toBe("true");
  });

  it("reads an aborted run's message as prose, never as rule slugs", async () => {
    // `failed` stores a bare `str(exc)`. Its own "word: detail" shape would be
    // mistaken for a slug list, inventing a rule that never existed.
    const scope = await mount(
      <EvaluationRunSummary
        run={run({
          status: "failed",
          rules_evaluated: 0,
          error_message: "connection lost: the pooler dropped the session"
        })}
        onDismiss={() => {}}
      />
    );

    expect(scope.textContent).toContain("connection lost: the pooler dropped the session");
    expect(scope.querySelector(".font-mono")).toBeNull();
    expect(scope.textContent).toContain("Evaluation stopped before it finished");
  });

  it("says a clean run changed nothing rather than showing bare zeros", async () => {
    const scope = await mount(
      <EvaluationRunSummary
        run={run({ status: "done", results_created: 0, results_removed: 0 })}
        onDismiss={() => {}}
      />
    );

    expect(scope.textContent).toContain("Evaluation finished with no changes");
  });
});
