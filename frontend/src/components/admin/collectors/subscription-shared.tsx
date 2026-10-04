"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { TintedBadge } from "@/components/admin/TintedBadge";
import type { Tone } from "@/components/kit/tone";
import type { SubscriptionCollectionStats } from "@/types/admin.types";

import type { CollectorHealth } from "./collector-state";

export { formatDate, formatRelative, formatInterval } from "@/components/kit/format-time";

/** Tone per check state, handed to `TintedBadge` as the domain's vocabulary. */
const STATE_TONES: Record<string, Tone> = {
  active: "success",
  inactive: "warning",
  unknown: "info",
  error: "danger"
};

/** Solid fill per state, for the stacked distribution bar. */
export const STATE_BAR: Record<string, string> = {
  active: "bg-success",
  inactive: "bg-warning",
  unknown: "bg-info",
  error: "bg-danger"
};

/** Canonical display order for states. */
export const STATE_ORDER = ["active", "inactive", "unknown", "error"] as const;

/** Canonical display order for check triggers. `check_in` in particular must
 *  never reach a table cell with its underscore intact. */
export const SOURCE_ORDER = ["scheduled", "registration", "check_in", "manual", "redeem"] as const;

/** Providers the subscription domain can verify. Lookups fall back to the raw
 *  key, so a provider added backend-side still renders, just less prettily. */
export const PROVIDER_LABELS: Record<string, string> = {
  boosty: "Boosty",
  twitch: "Twitch"
};

/**
 * Display wording for the subscription domain's machine tokens, in the UI
 * language: check states, check triggers, and the reason codes the provider
 * resolvers emit.
 *
 * A hook rather than three constant maps: badges, tables, filters and the
 * person panels all name the same tokens, and a module-level map would have to
 * pin a locale. An unknown reason code falls back to the raw code rather than a
 * generic string — a reason added backend-side must still be readable, just
 * less prettily.
 */
export function useSubscriptionLabels() {
  const t = useTranslations("collectors.subscriptions");
  return useMemo(
    () => ({
      state: Object.fromEntries(STATE_ORDER.map((s) => [s, t(`state.${s}`)])) as Record<
        string,
        string
      >,
      source: Object.fromEntries(SOURCE_ORDER.map((s) => [s, t(`sourceLabel.${s}`)])) as Record<
        string,
        string
      >,
      reason: (code: string) => {
        const key = `reason.${code}` as "reason.not_subscribed";
        return t.has(key) ? t(key) : code;
      }
    }),
    [t]
  );
}

export function StateBadge({ state }: Readonly<{ state: string | null }>) {
  const t = useTranslations("collectors.subscriptions.state");
  const labels = useSubscriptionLabels();
  return (
    <TintedBadge value={state} tones={STATE_TONES} labels={labels.state} fallback={t("never")} />
  );
}

/**
 * Health marker for the Subscriptions tab of the collectors bar (F14).
 *
 * Same ordering rule as `rankHealthDot`: paused explains everything else, then
 * the 24h failure rate, then entitlements sitting in a failed state. `error`
 * here means the provider call itself did not conclude — a real outage, unlike
 * `inactive`, which is a legitimate verdict. The word for the state lives in
 * `collectors.common.health`, because this is not a component.
 */
export function subscriptionHealthDot(stats: SubscriptionCollectionStats): CollectorHealth {
  if (!stats.enabled) return { tone: "neutral", state: "paused" };
  if ((stats.error_rate_24h ?? 0) >= 0.2) return { tone: "danger", state: "failing" };
  if ((stats.by_state?.error ?? 0) > 0) return { tone: "warning", state: "degraded" };
  return { tone: "success", state: "healthy" };
}
