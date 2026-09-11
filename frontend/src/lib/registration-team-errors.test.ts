import { describe, expect, it } from "bun:test";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import { ApiError } from "@/lib/api-error";
import {
  REGISTRATION_TEAM_ERROR_CODES,
  isRetryableRegistrationTeamError,
  registrationTeamErrorCode,
  translateRegistrationTeamError,
} from "@/lib/registration-team-errors";

/**
 * The point of this file: every machine code the backend can return must have a
 * translation in BOTH locales.
 *
 * `messages.parity.test.ts` only proves en and ru agree with each other — two
 * dictionaries can be perfectly symmetric and still both be missing a code. This
 * is the test that ties the code list to the dictionaries, so adding a backend
 * rejection without translating it fails here rather than shipping English text to
 * a Russian user (§12.2).
 */

const enErrors = (en as Record<string, Record<string, Record<string, string>>>).registrationTeams
  .errors;
const ruErrors = (ru as Record<string, Record<string, Record<string, string>>>).registrationTeams
  .errors;

/** A translator over one dictionary, shaped like next-intl's scoped `t`. */
function translator(dict: Record<string, string>) {
  const t = (key: string) => dict[key] ?? `registrationTeams.errors.${key}`;
  return Object.assign(t, { has: (key: string) => key in dict });
}

function apiError(status: number, ...codes: string[]) {
  return new ApiError(
    status,
    codes.map((code) => ({ code, msg: `English server text for ${code}` })),
  );
}

describe("registration team error codes", () => {
  it("every code has an English translation", () => {
    const missing = REGISTRATION_TEAM_ERROR_CODES.filter((code) => !(code in enErrors));
    expect(missing).toEqual([]);
  });

  it("every code has a Russian translation", () => {
    const missing = REGISTRATION_TEAM_ERROR_CODES.filter((code) => !(code in ruErrors));
    expect(missing).toEqual([]);
  });


  it("actually differs between locales", () => {
    // Guards a copy-paste of the English tree into ru.json, which would pass every
    // key-based assertion above while shipping English to Russian users.
    const identical = REGISTRATION_TEAM_ERROR_CODES.filter(
      (code) => enErrors[code] === ruErrors[code],
    );
    expect(identical).toEqual([]);
  });

  it("no Russian message is left in Latin script", () => {
    const latinOnly = REGISTRATION_TEAM_ERROR_CODES.filter(
      (code) => !/[\u0400-\u04FF]/.test(ruErrors[code] ?? ""),
    );
    expect(latinOnly).toEqual([]);
  });
});

describe("translateRegistrationTeamError", () => {
  it("prefers the translated code over the server's English message", () => {
    const message = translateRegistrationTeamError(
      translator(ruErrors),
      apiError(409, "slot_taken"),
    );
    expect(message).toBe(ruErrors.slot_taken);
    expect(message).not.toContain("English server text");
  });

  it("returns the first recognized code when several arrive", () => {
    const message = translateRegistrationTeamError(
      translator(enErrors),
      apiError(409, "not_a_real_code", "bench_full"),
    );
    expect(message).toBe(enErrors.bench_full);
  });

  it("keeps unknown server failures localized", () => {
    expect(translateRegistrationTeamError(
      translator(ruErrors),
      apiError(500, "brand_new_backend_code"),
    )).toBe(ruErrors.request_failed);
  });

  it("falls back for a non-ApiError throw", () => {
    expect(translateRegistrationTeamError(translator(enErrors), new Error("boom"))).toBe(enErrors.request_failed);
    expect(translateRegistrationTeamError(translator(enErrors), null, "fallback")).toBe("fallback");
  });

  it("works with a translator that has no `has`", () => {
    // The static code table is the membership test in that case — which is why it
    // must stay exhaustive.
    const plain = (key: string) => `translated:${key}`;
    expect(translateRegistrationTeamError(plain, apiError(409, "slot_taken"))).toBe(
      "translated:slot_taken",
    );
  });
});

describe("registrationTeamErrorCode", () => {
  it("extracts a known code", () => {
    expect(registrationTeamErrorCode(apiError(409, "invite_expired"))).toBe("invite_expired");
  });

  it("ignores codes it does not own", () => {
    expect(registrationTeamErrorCode(apiError(500, "internal"))).toBeNull();
    expect(registrationTeamErrorCode(new Error("boom"))).toBeNull();
  });
});

describe("isRetryableRegistrationTeamError", () => {
  it("treats throttling and limiter outages as retryable", () => {
    for (const code of ["invite_rate_limited", "accept_rate_limited", "rate_limit_unavailable"]) {
      expect(isRetryableRegistrationTeamError(apiError(429, code))).toBe(true);
    }
  });

  it("does not offer a retry when the user must change something first", () => {
    // Retrying `slot_taken` or `team_name_taken` unchanged can only fail again.
    for (const code of ["slot_taken", "team_name_taken", "invite_expired", "not_captain"]) {
      expect(isRetryableRegistrationTeamError(apiError(409, code))).toBe(false);
    }
  });
});
