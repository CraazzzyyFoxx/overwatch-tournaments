import type { Tone } from "@/components/kit/tone";
import type { StreamPollHealth, StreamPollStatus } from "@/types/admin.types";

/**
 * Wording and tone per recorded tick outcome.
 *
 * A registry rather than nested ternaries (the same reason `variant` in
 * `lib/tournament-status.ts` is a lookup): the compiler then holds this
 * exhaustive against `StreamPollStatus`, so a status added backend-side fails
 * the build here instead of silently rendering as a raw enum token.
 *
 * `hint` is the operator's next action, not a restatement of the label — the
 * whole reason the health panel exists is that the tick swallows its own
 * failures, so "what went wrong" without "what to do" leaves them back in the
 * logs.
 */
export const STREAM_STATUS_META: Record<
  StreamPollStatus,
  { label: string; tone: Tone; hint: string | null }
> = {
  ok: { label: "Last tick OK", tone: "success", hint: null },
  empty: {
    label: "Nothing to poll",
    tone: "neutral",
    hint: "The last tick found no active tournament with a Twitch channel attached. Add a stream link to a live tournament to give the poller something to do."
  },
  truncated: {
    label: "Tick cut short",
    tone: "warning",
    hint: "More channels were due than one tick could cover. Raise the batch size (up to Twitch's 100 ceiling) or lower the interval so the backlog drains."
  },
  not_configured: {
    label: "Twitch credentials missing",
    tone: "danger",
    hint: "Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in backend/env/stream.env, then restart stream-service."
  },
  rate_limited: {
    label: "Helix rate limit reached",
    tone: "warning",
    hint: "The 800 requests/min bucket is shared with identity-service's OAuth sign-ins, so exhausting it breaks logins, not just stream badges. Fix it by RAISING the poll interval (or lowering the batch size) — not by retrying."
  },
  unauthorized: {
    label: "Twitch rejected the credentials",
    tone: "danger",
    hint: "The credentials are present but Twitch refused them. Re-check the client id/secret pair in the Twitch developer console (a rotated or deleted app reads exactly like this) and update backend/env/stream.env."
  },
  unavailable: {
    label: "Twitch unreachable",
    tone: "warning",
    hint: "Twitch did not answer. Nothing to do on our side — the next tick retries. If it persists, check the Twitch status page and this worker's egress."
  },
  error: {
    label: "Tick failed",
    tone: "danger",
    hint: "The tick raised an unexpected error. Check the stream-service logs for the traceback — the tick swallows failures to keep the scheduler alive, so nothing else surfaces it."
  }
};

export interface StreamDiagnosis {
  tone: Tone;
  label: string;
  hint: string | null;
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
 * dashboard into the layout to get it.
 */
export function diagnoseStreamHealth(health: StreamPollHealth): StreamDiagnosis {
  if (!health.enabled) {
    return {
      tone: "neutral",
      label: "Polling is off",
      hint: "This is the shipped default — a fresh deploy never touches Twitch. Turn on background polling in the Settings tab to start it."
    };
  }

  // Checked ahead of `status`: an operator who has just filled in the env sees
  // this flip before the next tick overwrites a stale `not_configured`.
  if (!health.credentials_configured) {
    return {
      tone: "danger",
      label: STREAM_STATUS_META.not_configured.label,
      hint: STREAM_STATUS_META.not_configured.hint
    };
  }

  if (health.status === null) {
    return {
      tone: "info",
      label: "No tick recorded yet",
      hint: "Polling is on and configured, but the scheduler has not reached a due tick. This is not a failure — give it one interval."
    };
  }

  return STREAM_STATUS_META[health.status];
}

/** Health marker for the Streams tab of the collectors bar (F14): the same
 *  verdict the dashboard shows, minus the operator instructions. */
export function streamHealthDot(health: StreamPollHealth): { tone: Tone; label: string } {
  const { tone, label } = diagnoseStreamHealth(health);
  return { tone, label };
}
