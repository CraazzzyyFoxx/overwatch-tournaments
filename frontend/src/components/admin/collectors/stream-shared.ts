import type { Tone } from "@/components/kit/tone";
import type { StreamPollHealth, StreamPollStatus } from "@/types/admin.types";

/**
 * Tone per recorded tick outcome.
 *
 * A registry rather than nested ternaries (the same reason `variant` in
 * `lib/tournament/status.ts` is a lookup): the compiler then holds this
 * exhaustive against `StreamPollStatus`, so a status added backend-side fails
 * the build here instead of silently rendering as a raw enum token.
 *
 * The wording lives in `collectors.streams.status.<key>` — a `label` an
 * operator reads and a `hint` telling them what to do next, because the whole
 * reason the health panel exists is that the tick swallows its own failures, so
 * "what went wrong" without "what to do" leaves them back in the logs. An empty
 * `hint` (only `ok`) means there is nothing to do.
 */
export const STREAM_STATUS_TONES: Record<StreamPollStatus, Tone> = {
  ok: "success",
  empty: "neutral",
  truncated: "warning",
  not_configured: "danger",
  rate_limited: "warning",
  unauthorized: "danger",
  unavailable: "warning",
  error: "danger"
};

/** Message key under `collectors.streams.status`: a recorded outcome, or one of
 *  the two states that precede any outcome at all. */
export type StreamDiagnosisKey = StreamPollStatus | "off" | "no_tick";

export interface StreamDiagnosis {
  tone: Tone;
  key: StreamDiagnosisKey;
}

/**
 * The one thing the stream collector owes the operator.
 *
 * Three unrelated causes all render as "a tournament page with no live badges",
 * and they need different actions. Resolved in this order because each earlier
 * cause makes the later ones unobservable: a disabled poller never records a
 * status at all, and missing credentials can't be "rejected".
 *
 * Lives beside the vocabulary rather than in the dashboard because the tab bar
 * needs the same verdict for its health dot (F14) and must not drag a polling
 * dashboard into the layout to get it. Returns a message key rather than the
 * wording: this is a plain function, so it cannot reach a translator.
 */
export function diagnoseStreamHealth(health: StreamPollHealth): StreamDiagnosis {
  if (!health.enabled) return { tone: "neutral", key: "off" };

  // Checked ahead of `status`: an operator who has just filled in the env sees
  // this flip before the next tick overwrites a stale `not_configured`.
  if (!health.credentials_configured) return { tone: "danger", key: "not_configured" };

  if (health.status === null) return { tone: "info", key: "no_tick" };

  return { tone: STREAM_STATUS_TONES[health.status], key: health.status };
}
