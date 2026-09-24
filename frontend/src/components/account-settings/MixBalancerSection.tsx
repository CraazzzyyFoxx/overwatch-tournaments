"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Check, Scale } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { RosterShapeEditor } from "@/components/roster-shape/RosterShapeEditor";
import { ROSTER_SLOT_CODES } from "@/lib/roster/shape";
import { notify } from "@/lib/notify";
import {
  mixPreferencesKeys,
  mixPreferencesService,
  type MixBalancerPreferences,
  type MixBalancerPreferencesRead,
} from "@/services/mix-preferences.service";
import { Spinner } from "@/components/ui/spinner";

import {
  DEFAULT_COMFORT_TILT,
  DEFAULT_RESULT_VARIANTS,
  DEFAULT_ROLE_WEIGHT,
  MAX_POINTS_PER_WIN,
  MAX_RESULT_VARIANTS,
  MAX_ROLE_WEIGHT,
  SLOT_LABELS,
  draftOf,
  preferencesPayload,
  withRoleWeight,
} from "./mix-balancer-prefs";

/** How long a knob has to sit still before the row is written. */
const AUTOSAVE_DELAY_MS = 700;

/**
 * Everything about how a mix this account hosts is set up and balanced.
 *
 * These knobs used to live on each mix, which meant re-setting them for every
 * new game and storing the same numbers on every row. They describe how their
 * owner runs a pickup night, not anything about one night, so they sit here:
 * every mix this account hosts uses them -- the same account whose rank book a
 * mix already resolves against.
 *
 * There is no Save button. A settings panel with one is a panel that silently
 * discards work when it is closed with the mouse, and none of these writes is
 * destructive or expensive: each knob autosaves once it stops moving, and the
 * row is replaced whole. A knob left at its default is stored as nothing at
 * all, so an account that never opens this panel keeps an empty row.
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

  // A controlled draft rather than a derived value: the slider and the number
  // fields move far more often than the query refetches.
  const [draft, setDraft] = useState(() => draftOf(stored));
  const [seeded, setSeeded] = useState<MixBalancerPreferencesRead | undefined>(stored);
  const payload = preferencesPayload(draft);
  const dirty = seeded != null && !samePayload(payload, preferencesPayload(draftOf(seeded)));
  if (stored !== undefined && stored !== seeded) {
    setSeeded(stored);
    // A save that landed while the user kept typing must not roll their newer
    // edits back: the fresh row only becomes the baseline, and the still-dirty
    // draft simply schedules the next write.
    if (!dirty) setDraft(draftOf(stored));
  }

  const save = useMutation({
    mutationFn: (body: MixBalancerPreferences) => mixPreferencesService.update(body),
    onSuccess: (saved) => queryClient.setQueryData(mixPreferencesKeys.all, saved),
    onError: (error) => notify.apiError(error),
  });

  // Debounced on the serialised payload, so dragging the slider across the
  // track is one write rather than twenty, and a knob nudged back to where it
  // started writes nothing at all.
  const pendingPayload = JSON.stringify(payload);
  const { mutate } = save;
  useEffect(() => {
    if (!dirty) return;
    const timer = setTimeout(() => mutate(JSON.parse(pendingPayload)), AUTOSAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [pendingPayload, dirty, mutate]);

  if (preferencesQuery.isLoading) {
    return (
      <div className="space-y-4" aria-hidden>
        <Skeleton className="h-64 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  if (preferencesQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("mixBalancer.loadError")}
        onAction={() => void preferencesQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <RosterShapeEditor
        entity="account"
        value={draft.roleMask}
        effective={stored?.roster_shape ?? null}
        onChange={(roleMask) => setDraft((current) => ({ ...current, roleMask }))}
      />

      {/* Same card as the roster editor above, so the two halves of one
          autosaving form read as siblings rather than two different widgets. */}
      <Card className="border-border/40 bg-card/50">
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Scale className="size-4 text-primary" aria-hidden />
            <CardTitle asChild className="text-sm font-semibold">
              <h4>{t("mixBalancer.balancingTitle")}</h4>
            </CardTitle>
          </div>
          {/* One line, three states, no button: saving, saved, or nothing.
              It covers the roster shape too — both halves share one draft. */}
          <span
            role="status"
            aria-live="polite"
            className="flex items-center gap-1.5 text-xs text-[color:var(--aqt-fg-dim)]"
          >
            {save.isPending || dirty ? (
              <>
                <Spinner className="size-3" />
                {t("mixBalancer.saving")}
              </>
            ) : save.isSuccess ? (
              <>
                <Check className="h-3 w-3" aria-hidden />
                {t("mixBalancer.saved")}
              </>
            ) : null}
          </span>
        </CardHeader>

        <CardContent className="space-y-6">
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

          <div className="space-y-1.5">
            <Label htmlFor="mix-points-per-win">{t("mixBalancer.points.label")}</Label>
            <NumberInput
              id="mix-points-per-win"
              integer
              min={0}
              max={MAX_POINTS_PER_WIN}
              placeholder={t("mixBalancer.points.placeholder")}
              value={draft.pointsPerWin}
              onValueChange={(next) => setDraft((current) => ({ ...current, pointsPerWin: next }))}
              className="h-8 w-24 bg-background/50 px-2 tabular-nums"
            />
            <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("mixBalancer.points.hint")}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** Key order is stable (both sides come out of `preferencesPayload`), so this is a value compare. */
function samePayload(left: MixBalancerPreferences, right: MixBalancerPreferences): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
