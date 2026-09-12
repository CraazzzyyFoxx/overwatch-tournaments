"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { Slider } from "@/components/ui/slider";
import { ROSTER_SLOT_CODES } from "@/lib/roster-shape";
import { notify } from "@/lib/notify";
import {
  mixPreferencesKeys,
  mixPreferencesService,
  type MixBalancerPreferences,
} from "@/services/mix-preferences.service";

import {
  DEFAULT_COMFORT_TILT,
  DEFAULT_RESULT_VARIANTS,
  DEFAULT_ROLE_WEIGHT,
  MAX_RESULT_VARIANTS,
  MAX_ROLE_WEIGHT,
  SLOT_LABELS,
  preferencesPayload,
  roleWeightsOf,
  tiltOf,
  variantsOf,
  withRoleWeight,
} from "./mix-balancer-prefs";

/** The three knobs as the panel edits them, before they become a stored row. */
type Draft = {
  tilt: number;
  weights: Record<string, number>;
  variants: number;
};

function draftOf(preferences: MixBalancerPreferences | null | undefined): Draft {
  return {
    tilt: tiltOf(preferences),
    weights: roleWeightsOf(preferences),
    variants: variantsOf(preferences),
  };
}

/**
 * How the pickup-mix engine balances for this account.
 *
 * These knobs used to live on each mix, which meant re-setting them for every
 * new game and storing the same three numbers on every row. They describe how
 * their owner likes a lobby split, not anything about one night, so they sit
 * here instead: every mix this account hosts balances with them -- the same
 * account whose rank book a mix already resolves against.
 *
 * A knob left at its default is stored as nothing at all, so an account that
 * never opens this panel keeps an empty row and the engine's own weighting.
 */
export default function MixBalancerSection() {
  const t = useTranslations("accountSettings");
  const queryClient = useQueryClient();

  const preferencesQuery = useQuery({
    queryKey: mixPreferencesKeys.all,
    queryFn: () => mixPreferencesService.get(),
    staleTime: 60_000,
  });
  const stored = preferencesQuery.data;

  // Seeded from the row and re-seeded whenever a fetch lands a different one:
  // a controlled draft, not a derived value, because the slider and the number
  // fields move far more often than the query refetches.
  const [draft, setDraft] = useState<Draft>(() => draftOf(stored));
  const [seeded, setSeeded] = useState<MixBalancerPreferences | undefined>(stored);
  if (stored !== undefined && stored !== seeded) {
    setSeeded(stored);
    setDraft(draftOf(stored));
  }

  const payload = preferencesPayload(draft.tilt, draft.weights, draft.variants);
  const dirty =
    stored != null &&
    JSON.stringify(payload) !==
      JSON.stringify(
        preferencesPayload(tiltOf(stored), roleWeightsOf(stored), variantsOf(stored)),
      );

  const save = useMutation({
    mutationFn: () => mixPreferencesService.update(payload),
    onSuccess: (saved) => {
      queryClient.setQueryData(mixPreferencesKeys.all, saved);
      notify.success(t("mixBalancer.saved"));
    },
    onError: (error) => notify.apiError(error),
  });

  if (preferencesQuery.isLoading) {
    return (
      <Loader2
        className="h-4 w-4 animate-spin text-[color:var(--aqt-fg-muted)]"
        aria-label={t("mixBalancer.title")}
      />
    );
  }

  if (preferencesQuery.isError) {
    return <p className="text-sm text-[color:var(--aqt-fg-dim)]">{t("mixBalancer.loadError")}</p>;
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">
          {t("mixBalancer.title")}
        </h4>
        <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("mixBalancer.desc")}</p>

        <div className="space-y-6 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-3.5">
          <div className="space-y-1.5">
            <Label asChild>
              <span>{t("mixBalancer.tilt.label")}</span>
            </Label>
            <Slider
              aria-label={t("mixBalancer.tilt.label")}
              min={0}
              max={100}
              step={5}
              value={[Math.round(draft.tilt * 100)]}
              onValueChange={([next]) =>
                setDraft((current) => ({ ...current, tilt: (next ?? 50) / 100 }))
              }
            />
            <div className="flex justify-between text-xs text-[color:var(--aqt-fg-dim)]">
              <span>{t("mixBalancer.tilt.evenRanks")}</span>
              <span className="tabular-nums">
                {draft.tilt === DEFAULT_COMFORT_TILT
                  ? t("mixBalancer.tilt.balanced")
                  : t("mixBalancer.tilt.comfort", { percent: Math.round(draft.tilt * 100) })}
              </span>
              <span>{t("mixBalancer.tilt.preferredRoles")}</span>
            </div>
            <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("mixBalancer.tilt.hint")}</p>
          </div>

          <div className="space-y-1.5">
            <Label asChild>
              <span>{t("mixBalancer.weights.label")}</span>
            </Label>
            <div className="flex flex-wrap gap-2">
              {ROSTER_SLOT_CODES.map((code) => (
                <div key={code} className="flex items-center gap-2">
                  <Label
                    htmlFor={`mix-role-weight-${code}`}
                    className="text-xs text-[color:var(--aqt-fg-dim)]"
                  >
                    {SLOT_LABELS[code]}
                  </Label>
                  <NumberInput
                    id={`mix-role-weight-${code}`}
                    min={0}
                    max={MAX_ROLE_WEIGHT}
                    placeholder={String(DEFAULT_ROLE_WEIGHT)}
                    value={draft.weights[code] ?? DEFAULT_ROLE_WEIGHT}
                    onValueChange={(next) =>
                      setDraft((current) => ({
                        ...current,
                        weights: withRoleWeight(current.weights, code, next),
                      }))
                    }
                    className="h-8 w-16 bg-background/50 px-2 text-center tabular-nums"
                  />
                </div>
              ))}
            </div>
            <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("mixBalancer.weights.hint")}</p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="mix-result-variants">{t("mixBalancer.variants.label")}</Label>
            <NumberInput
              id="mix-result-variants"
              integer
              min={1}
              max={MAX_RESULT_VARIANTS}
              placeholder={String(DEFAULT_RESULT_VARIANTS)}
              value={draft.variants}
              onValueChange={(next) =>
                setDraft((current) => ({ ...current, variants: next ?? DEFAULT_RESULT_VARIANTS }))
              }
              className="h-8 w-24 bg-background/50 px-2 tabular-nums"
            />
            <p className="text-xs text-[color:var(--aqt-fg-dim)]">
              {t("mixBalancer.variants.hint", { max: MAX_RESULT_VARIANTS })}
            </p>
          </div>

          <div className="flex justify-end">
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? t("mixBalancer.saving") : t("mixBalancer.save")}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
