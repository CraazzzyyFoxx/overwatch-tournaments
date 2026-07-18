export interface ApiErrorDetail {
  msg: string;
  code: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly details: ApiErrorDetail[];

  constructor(status: number, details: ApiErrorDetail[]) {
    const message = details.map((d) => d.msg).join("\n");
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/**
 * True when a thrown value represents "resource not found" — either an HTTP 404
 * or a business error whose code is `not_found`. Some backend lookups signal a
 * missing entity with 400 + code "not_found" (e.g. user-by-name), so a bare
 * `status === 404` check is not enough. Use to map to Next's notFound()/404
 * metadata instead of letting it bubble up as a 500.
 */
export function isNotFoundError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 404 || error.details.some((d) => d.code === "not_found"))
  );
}

/**
 * True when a captain result submission was rejected because the encounter's
 * result is already locked (confirmed). The tournament backend answers such
 * attempts with 400 and a detail string like
 * `Cannot submit: result status is 'confirmed'`. Callers use this to swap the
 * raw backend string for a friendly "ask an admin" message and refresh stale
 * UI so the report action disappears.
 */
export function isResultLockedError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    error.details.some((d) => /result status is 'confirmed'/i.test(d.msg))
  );
}

/**
 * True when a captain match report was rejected because the encounter is no
 * longer in a reportable state — either already confirmed or already submitted
 * and pending the other captain's confirmation. The backend answers with 400
 * and a detail like `Cannot submit: result status is '<status>'`. Callers use
 * this to show a friendly, state-specific message and refresh stale UI.
 */
export function isResultNotReportableError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    error.details.some((d) => /Cannot submit: result status is/i.test(d.msg))
  );
}

/**
 * True when a captain tried to confirm a result they submitted themselves. The
 * backend rejects this with 400 and a detail like
 * `Cannot confirm your own submission - the other captain must confirm`.
 * Callers swap the raw string for a friendly localized message.
 */
export function isConfirmOwnSubmissionError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    error.details.some((d) => /confirm your own submission/i.test(d.msg))
  );
}

// ─── Parsing ──────────────────────────────────────────────────────────────────

const PYDANTIC_LOC_PREFIXES = ["body", "query", "path", "header", "cookie"];

/** Render a pydantic `loc` tuple into a readable field path (dropping the source prefix). */
function formatPydanticLoc(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  return loc
    .map((part) => String(part))
    .filter((part, index) => !(index === 0 && PYDANTIC_LOC_PREFIXES.includes(part)))
    .join(".");
}

/**
 * Normalize a single `detail` entry into one or more {msg, code}.
 *
 * Handles the backend shapes:
 *   - string                                   (wrapped HTTPException)
 *   - { msg: string, code }                    (business error)
 *   - { msg: [pydantic errors], code }         (422 validation – msg is an array)
 */
function normalizeDetailItem(item: unknown): ApiErrorDetail[] {
  if (typeof item === "string") {
    return [{ msg: item, code: "error" }];
  }

  if (item && typeof item === "object") {
    const obj = item as { msg?: unknown; message?: unknown; code?: string };
    const code = obj.code ?? "unknown";
    const rawMsg = obj.msg ?? obj.message;

    // 422: msg is the raw pydantic error array → expand into readable lines.
    if (Array.isArray(rawMsg)) {
      const lines = rawMsg.map((entry) => {
        const pe = (entry ?? {}) as { loc?: unknown; msg?: unknown };
        const loc = formatPydanticLoc(pe.loc);
        const peMsg = typeof pe.msg === "string" ? pe.msg : "Invalid value";
        return { msg: loc ? `${loc}: ${peMsg}` : peMsg, code };
      });
      return lines.length > 0 ? lines : [{ msg: "Invalid input", code }];
    }

    if (typeof rawMsg === "string") {
      return [{ msg: rawMsg, code }];
    }

    return [{ msg: "Unknown error", code }];
  }

  return [{ msg: "Unknown error", code: "unknown" }];
}

/**
 * Parse a non-ok Response into an ApiError.
 *
 * Expected backend shapes (see backend/shared/core/errors.py & middleware.py):
 *   { "detail": [{ "msg": "…", "code": "…" }] }            – business error
 *   { "detail": [{ "msg": [pydantic…], "code": "…" }] }    – 422 validation
 *   { "detail": ["some string"] } / { "detail": "string" } – wrapped HTTPException
 *   { "message": "some string" }                            – fallback
 */
export async function parseApiError(response: Response): Promise<ApiError> {
  let details: ApiErrorDetail[];

  try {
    const body = await response.json();
    const raw = body?.detail ?? body?.message;

    if (Array.isArray(raw)) {
      details = raw.flatMap(normalizeDetailItem);
      if (details.length === 0) {
        details = [{ msg: "An error occurred", code: "unknown" }];
      }
    } else if (typeof raw === "string") {
      details = [{ msg: raw, code: "error" }];
    } else {
      details = [{ msg: "An error occurred", code: "unknown" }];
    }
  } catch {
    details = [{ msg: "An error occurred", code: "unknown" }];
  }

  return new ApiError(response.status, details);
}

// ─── Presentation helpers ──────────────────────────────────────────────────────

/** Fallback friendly messages keyed by machine error code. Server `msg` is preferred. */
const ERROR_CODE_MESSAGES: Record<string, string> = {
  Unknown: "Something went wrong. Please try again.",
  unknown: "Something went wrong. Please try again.",
  request_too_large: "The request is too large.",
  unprocessable_entity: "Some of the submitted values are invalid."
};

function friendlyMessage(detail: ApiErrorDetail): string {
  if (detail.msg && detail.msg !== detail.code) return detail.msg;
  return ERROR_CODE_MESSAGES[detail.code] ?? detail.msg ?? detail.code;
}

function defaultTitleForStatus(status: number): string {
  if (status === 401) return "Unauthorized";
  if (status === 403) return "Access denied";
  if (status === 404) return "Not found";
  if (status === 429) return "Too many requests";
  if (status >= 500) return "Server error";
  return "Request failed";
}

/**
 * Extract a single human-readable string from any thrown value.
 * Use for inline error states; `describeApiError` is preferred for toasts.
 */
export function getApiErrorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof ApiError) {
    const msg = error.details.map(friendlyMessage).filter(Boolean).join("\n").trim();
    return msg || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  if (typeof error === "string") {
    return error || fallback;
  }
  return fallback;
}

/**
 * Split any thrown value into a toast-friendly { title, description }.
 * Validation (422) errors are grouped under a single title with field lines as the description.
 */
export function describeApiError(error: unknown): { title: string; description?: string } {
  if (error instanceof ApiError) {
    const lines = error.details.map(friendlyMessage).filter(Boolean);

    if (error.status === 422 || error.details.some((d) => d.code === "unprocessable_entity")) {
      return {
        title: "Validation error",
        description: lines.join("\n") || undefined
      };
    }

    if (lines.length === 0) {
      return { title: defaultTitleForStatus(error.status) };
    }
    if (lines.length === 1) {
      return { title: lines[0] };
    }
    return { title: defaultTitleForStatus(error.status), description: lines.join("\n") };
  }

  if (error instanceof Error) {
    return { title: error.message || "Error" };
  }
  if (typeof error === "string") {
    return { title: error || "Error" };
  }
  return { title: "Something went wrong" };
}
