import { describe, expect, it } from "vitest";

import {
  ADMISSION_ORDER,
  ADMISSION_REASON_CODES,
  ADMISSION_SEARCH_TEXT,
  formatAdmissionReason,
  primaryAdmissionReason,
  type AdmissionTranslator
} from "@/lib/registration/admission";
import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { Admission, AdmissionReason, RequirementVerdict } from "@/types/registration.types";

const verdict = (overrides: Partial<RequirementVerdict> = {}): RequirementVerdict => ({
  key: "subscription",
  state: "undetermined",
  stage: "check_in",
  reasons: [],
  detail: {},
  ...overrides
});

const admission = (requirements: RequirementVerdict[], blockers: RequirementVerdict[] = []): Admission => ({
  decision: blockers.length > 0 ? "not_admitted" : "pending_check_in",
  requirements,
  blockers,
  overridden: [],
  checked_in: false,
  ready: true
});

const reason = (code: string, actor: AdmissionReason["actor"]): AdmissionReason => ({
  code,
  actor,
  subject: null
});

/** A translator with no `has`, exactly like the test doubles the column builders
 *  are handed — this is the path that falls back to the static code list. */
const bareTranslator = ((key: string) => `t:${key}`) as unknown as AdmissionTranslator;

describe("i18n completeness", () => {
  it("has a message for every reason code, in both locales", () => {
    // Without this, a code added on the backend surfaces in the UI as raw
    // snake_case — and the fallback that prevents a blank cell also hides the
    // omission, so nothing else would ever fail.
    for (const messages of [en, ru]) {
      expect(Object.keys(messages.admission.reason).sort()).toEqual(
        [...ADMISSION_REASON_CODES].sort()
      );
    }
  });

  it("keeps the two locales structurally identical under `admission`", () => {
    expect(Object.keys(en.admission).sort()).toEqual(Object.keys(ru.admission).sort());
    expect(Object.keys(en.admission.requirement).sort()).toEqual(
      Object.keys(ru.admission.requirement).sort()
    );
  });
});

describe("formatAdmissionReason", () => {
  it("falls back to the raw code for something the catalogue does not know", () => {
    expect(formatAdmissionReason(bareTranslator, reason("moon_phase", "system"))).toBe(
      "moon_phase"
    );
  });

  it("appends the subject, because that is what disambiguates", () => {
    expect(
      formatAdmissionReason(bareTranslator, {
        code: "profile_private",
        actor: "player",
        subject: "Player#2100"
      })
    ).toBe("t:admission.reason.profile_private (Player#2100)");
  });
});

describe("primaryAdmissionReason", () => {
  it("prefers a blocker over a requirement that is merely failing open", () => {
    const blocker = verdict({
      key: "open_profile",
      state: "blocked",
      reasons: [reason("profile_private", "player")]
    });
    const pending = verdict({ reasons: [reason("provider_unavailable", "system")] });

    expect(primaryAdmissionReason(admission([pending, blocker], [blocker]))?.code).toBe(
      "profile_private"
    );
  });

  it("falls back to the first undetermined requirement, so an outage is still visible", () => {
    const pending = verdict({ reasons: [reason("provider_unavailable", "system")] });

    expect(primaryAdmissionReason(admission([pending]))?.code).toBe("provider_unavailable");
  });

  it("is null when nothing is unresolved", () => {
    expect(primaryAdmissionReason(admission([verdict({ state: "satisfied" })]))).toBeNull();
  });
});

describe("column projections", () => {
  it("orders the sort worst-first and keeps the search text distinct", () => {
    expect(ADMISSION_ORDER.not_admitted).toBeLessThan(ADMISSION_ORDER.pending_check_in);
    expect(ADMISSION_ORDER.pending_check_in).toBeLessThan(ADMISSION_ORDER.admitted);
    expect(new Set(Object.values(ADMISSION_SEARCH_TEXT)).size).toBe(3);
  });
});
