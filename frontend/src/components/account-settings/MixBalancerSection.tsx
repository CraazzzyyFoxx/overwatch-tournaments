"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ratedDimension, selectableRoles } from "@/lib/roster/ontology";
import { useGameScope } from "@/hooks/useGameScope";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useRoleName } from "@/hooks/useRoleName";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { BanPresetSelect } from "@/components/pick-ban/BanPresetSelect";
import { MixFormationControl } from "@/components/mix/MixFormationControl";
import { notify } from "@/lib/notify";
import {
  mixPreferencesKeys,
  mixPreferencesService,
  type MixBalancerPreferences,
  type MixBalancerPreferencesRead,
  type MixRatingMode,
} from "@/services/mix-preferences.service";
import { Spinner } from "@/components/ui/spinner";

import {
  DEFAULT_COMFORT_TILT,
  DEFAULT_RESULT_VARIANTS,
  DEFAULT_ROLE_WEIGHT,
  MAX_POINTS_PER_WIN,
  MAX_RESULT_VARIANTS,
  MAX_ROLE_WEIGHT,
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
  // A platform section (spec §5): the preferences are the player's, so its game tabs list every installed game.
  const gameScope = useGameScope({ pageClass: "platform", axis: "all" });
  const code = gameScope.game;
  const metadata = useDisciplineMetadata(gameScope.axis, code);
  const rated = metadata.data ? ratedDimension(metadata.data) : null;
  const roleT = useTranslations("common.roleOntology");
  const nameOf = useRoleName();
  const weightRoles = metadata.data && rated ? selectableRoles(metadata.data, rated.code).filter(role => role.workspace_id === null && role.parent_id === null) : [];

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
    // The two groups below, row for row: `true` marks a stacked row.
    const groups = [
      { id: "mixes-balancing", title: t("mixBalancer.balancingTitle"), description: undefined, rows: [true, true, false, false, false] },
      { id: "mixes-defaults", title: t("mixBalancer.defaultsTitle"), description: t("mixBalancer.defaultsDesc"), rows: [false, true] },
    ];
    return (
      <div className="space-y-6">
        {groups.map((group) => (
          <SettingGroup key={group.id} id={group.id} level={4} title={group.title} description={group.description}>
            {group.rows.map((stacked, index) => (
              <div
                key={index}
                aria-hidden
                className={cn(
                  "grid gap-2 py-3 first:pt-0 last:pb-0",
                  !stacked && "@xl:grid-cols-2 @xl:items-center @xl:gap-6",
                )}
              >
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-3 w-full max-w-xs" />
                </div>
                <Skeleton className={stacked ? "h-8 w-full" : "h-8 w-24 @xl:justify-self-end"} />
              </div>
            ))}
          </SettingGroup>
        ))}
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Switching game mid-save would write one game's knobs under another's roles: the tabs wait for the save. */}
        <fieldset disabled={dirty || save.isPending} className="m-0 min-w-0 border-0 p-0">
          <GameScopeControl scope={gameScope} variant="single" />
        </fieldset>
        {/* One line, three states, no button: saving, saved, or nothing.
            It covers the roster shape too — both groups share one draft. */}
        <span
          role="status"
          aria-live="polite"
          className="ms-auto flex items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)]"
        >
          {save.isPending || dirty ? (
            <>
              <Spinner className="size-3" />
              {t("mixBalancer.saving")}
            </>
          ) : save.isSuccess ? (
            <>
              <Check className="size-3" aria-hidden />
              {t("mixBalancer.saved")}
            </>
          ) : null}
        </span>
      </div>

      <SettingGroup id="mixes-balancing" level={4} title={t("mixBalancer.balancingTitle")}>
        {/* No `htmlFor`: the slider's thumb is not labelable, so it carries its own name. */}
        <SettingRow label={t("mixBalancer.tilt.label")} hint={t("mixBalancer.tilt.hint")} stacked>
          <div className="w-full space-y-1.5">
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
            <div className="flex justify-between text-caption text-[color:var(--aqt-fg-dim)]">
              <span>{t("mixBalancer.tilt.evenRanks")}</span>
              <span className="aqt-tnum">
                {draft.tilt === DEFAULT_COMFORT_TILT
                  ? t("mixBalancer.tilt.balanced")
                  : t("mixBalancer.tilt.comfort", { percent: Math.round(draft.tilt * 100) })}
              </span>
              <span>{t("mixBalancer.tilt.preferredRoles")}</span>
            </div>
          </div>
        </SettingRow>

        <SettingRow
          label={t("mixBalancer.weights.label")}
          hint={t("mixBalancer.weights.hint")}
          error={metadata.isError || (metadata.data && !rated) ? roleT("metadataError") : undefined}
          stacked
        >
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {code && !metadata.isError && rated && [...weightRoles.map(role => ({ code: role.code, name: nameOf(role) })), { code: "flex", name: roleT("openSlot") }].map(({ code, name }) => (
              <div key={code} className="flex items-center gap-2">
                <Label
                  htmlFor={`mix-role-weight-${code}`}
                  className="text-caption font-normal text-[color:var(--aqt-fg-muted)]"
                >
                  {name}
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
                  size="sm"
                  className="w-16"
                />
              </div>
            ))}
          </div>
        </SettingRow>

        <SettingRow
          htmlFor="mix-result-variants"
          label={t("mixBalancer.variants.label")}
          hint={t("mixBalancer.variants.hint", { max: MAX_RESULT_VARIANTS })}
        >
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
            size="sm"
            className="w-24"
          />
        </SettingRow>

        <SettingRow
          htmlFor="mix-rating-mode"
          label={t("mixBalancer.mode.label")}
          hint={draft.ratingMode === "ranker" ? t("mixBalancer.mode.hint") : undefined}
        >
          <Select
            value={draft.ratingMode}
            onValueChange={(next) =>
              setDraft((current) => ({ ...current, ratingMode: next as MixRatingMode }))
            }
          >
            <SelectTrigger id="mix-rating-mode" size="sm" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="points">{t("mixBalancer.mode.points")}</SelectItem>
              <SelectItem value="ranker">{t("mixBalancer.mode.ranker")}</SelectItem>
            </SelectContent>
          </Select>
        </SettingRow>

        <SettingRow
          htmlFor="mix-points-per-win"
          label={t("mixBalancer.points.label")}
          hint={t("mixBalancer.points.hint")}
        >
          <NumberInput
            id="mix-points-per-win"
            integer
            min={0}
            max={MAX_POINTS_PER_WIN}
            // Kept, not cleared: switching back to points restores the number.
            disabled={draft.ratingMode === "ranker"}
            placeholder={t("mixBalancer.points.placeholder")}
            value={draft.pointsPerWin}
            onValueChange={(next) => setDraft((current) => ({ ...current, pointsPerWin: next }))}
            size="sm"
            className="w-24"
          />
        </SettingRow>
      </SettingGroup>

      {code != null ? (
        // One description for both rows: each value is copied into a new mix the same way.
        <SettingGroup
          id="mixes-defaults"
          level={4}
          title={t("mixBalancer.defaultsTitle")}
          description={t("mixBalancer.defaultsDesc")}
        >
          <SettingRow htmlFor="mix-ban-default" label={t("mixBalancer.bans.label")}>
            <BanPresetSelect
              id="mix-ban-default"
              discipline={code}
              label={t("mixBalancer.bans.label")}
              value={draft.banPresets[code] ?? null}
              onChange={(next) =>
                setDraft((current) => {
                  const banPresets = { ...current.banPresets };
                  if (next == null) delete banPresets[code];
                  else banPresets[code] = next;
                  return { ...current, banPresets };
                })
              }
            />
          </SettingRow>

          <SettingRow htmlFor={`mix-formation-${code}-formation`} label={t("mixBalancer.formation.label")} stacked>
            <MixFormationControl
              idPrefix={`mix-formation-${code}`}
              value={draft.formationDefaults[code] ?? { team_formation: "balance", draft_pick_seconds: 30 }}
              onChange={(next) =>
                setDraft((current) => ({
                  ...current,
                  formationDefaults: { ...current.formationDefaults, [code]: next },
                }))
              }
            />
          </SettingRow>
        </SettingGroup>
      ) : null}
    </div>
  );
}

/** Key order is stable (both sides come out of `preferencesPayload`), so this is a value compare. */
function samePayload(left: MixBalancerPreferences, right: MixBalancerPreferences): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
