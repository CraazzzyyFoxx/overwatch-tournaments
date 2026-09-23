import { describe, expect, it } from "bun:test";

import { fieldErrorsFrom, type Translate } from "@/lib/forms/form-errors";
import { parseApiError } from "@/lib/api/error";

/**
 * The point of this file: a per-field rejection must survive the gateway's error
 * body with its `code` and `field` attached.
 *
 * A worker raises `ApiHTTPException([ApiExc(msg, code, field), …])`; the RPC
 * envelope carries the items under `error.details.fields` and the v1 gateway
 * spreads that next to `detail`/`code` (`gateway/internal/apierr.WriteError`).
 * `detail` is only the human texts joined into one string — parsing THAT was how
 * two field errors became one anonymous banner and `fieldErrorsFrom` had nothing
 * to attach to an input.
 */

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** The exact 422 a registration PATCH with two bad answers produces. */
const REGISTRATION_422 = {
  code: "unprocessable",
  detail: "Invalid format.; Not one of the options.",
  fields: [
    { field: "battle_tag", msg: "Invalid format.", code: "invalid_format" },
    { field: "server", msg: "Not one of the options.", code: "invalid_option" },
  ],
};

describe("parseApiError", () => {
  it("keeps each field rejection's own code and field", async () => {
    const error = await parseApiError(response(422, REGISTRATION_422));

    expect(error.status).toBe(422);
    expect(error.details).toEqual([
      { msg: "Invalid format.", code: "invalid_format", field: "battle_tag" },
      { msg: "Not one of the options.", code: "invalid_option", field: "server" },
    ]);
  });

  it("reaches the form as two field messages, not one banner", async () => {
    const t: Translate = Object.assign((key: string) => `ru:${key}`, {
      has: () => true,
    }) as Translate;

    const result = fieldErrorsFrom(await parseApiError(response(422, REGISTRATION_422)), t);

    expect(result.fields).toEqual({
      battle_tag: "ru:invalid_format",
      server: "ru:invalid_option",
    });
    expect(result.form).toBeNull();
  });

  it("reads a whole-request rejection that names a request key", async () => {
    const error = await parseApiError(
      response(409, {
        code: "conflict",
        detail: "The registration form changed; reload and try again.",
        fields: [
          {
            field: "form_version_id",
            msg: "The registration form changed; reload and try again.",
            code: "form_version_stale",
          },
        ],
      }),
    );

    expect(error.details).toEqual([
      {
        msg: "The registration form changed; reload and try again.",
        code: "form_version_stale",
        field: "form_version_id",
      },
    ]);
  });

  it("reads the v2 body, where the entries sit under error.details", async () => {
    const error = await parseApiError(
      response(422, {
        ok: false,
        error: {
          code: "unprocessable",
          message: "Invalid format.",
          details: { fields: [{ field: "battle_tag", msg: "Invalid format.", code: "invalid_format" }] },
        },
      }),
    );

    expect(error.details).toEqual([
      { msg: "Invalid format.", code: "invalid_format", field: "battle_tag" },
    ]);
  });

  it("falls back to detail when nothing structured came with it", async () => {
    const error = await parseApiError(response(404, { detail: "Tournament not found", code: "not_found" }));

    expect(error.details).toEqual([{ msg: "Tournament not found", code: "not_found" }]);
  });

  it("ignores a `fields` key that is not a list of error items", async () => {
    // `fields` is also an ordinary query/response key; entries without a `msg`
    // are not rejections and must not replace the real message.
    const error = await parseApiError(
      response(400, { detail: "bad request", code: "bad_request", fields: ["name", "size"] }),
    );

    expect(error.details).toEqual([{ msg: "bad request", code: "bad_request" }]);
  });

  it("still expands a pydantic detail array", async () => {
    const error = await parseApiError(
      response(422, { detail: [{ msg: [{ loc: ["body", "name"], msg: "Field required" }], code: "invalid" }] }),
    );

    expect(error.details).toEqual([{ msg: "name: Field required", code: "invalid", field: "name" }]);
  });
});
