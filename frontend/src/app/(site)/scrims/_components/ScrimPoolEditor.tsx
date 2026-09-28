"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldSet,
  FieldTitle
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { PickBanRuleset, PickBanRulesetStep } from "@/types/tournament.types";

import {
  emptyPickBanDraft,
  emptyRuleset,
  matchesItemName,
  validatePickBanDraft,
  type PickBanDraft,
  type PickBanValidationIssue
} from "@/lib/tournament/pick-ban-config";
import { Spinner } from "@/components/ui/spinner";
import { useHeroesCatalog } from "@/hooks/useHeroesCatalog";
import { useMapsCatalog } from "@/hooks/useMapsCatalog";

/**
 * A room's hand-authored pick-ban rules.
 *
 * Holds the organizer editor's `PickBanDraft` verbatim — same model, same
 * converter, same validator (`pickBanConfig.helpers`) — so a form this editor
 * accepts is a payload the server accepts too.
 *
 * Two drafts, because a room configures at most two kinds and the hero one is
 * optional: `hero == null` ships a map-only room.
 */
export interface ScrimPoolDraft {
  map: PickBanDraft;
  hero: PickBanDraft | null;
}

/** Bans each side takes in a hero round, when hero bans are enabled. */
const DEFAULT_HERO_BANS_PER_SIDE = 2;
const MAX_HERO_BANS_PER_SIDE = 6;

/**
 * A hero round's ruleset: `n` bans per side, alternating, no picks and no
 * decider, each ban alive for the map it was taken on.
 *
 * A hero pool stays playable after its bans, so there is nothing for a decider
 * to resolve to. Generated from one number rather than authored step by step:
 * every hero order a scrim would want is this one with a different `n`, and the
 * organizer constructor is where anything else belongs.
 *
 * `uniqueRole` is the `max_per_group` constraint the tournament rules call
 * "one hero per role per round" — the same shape v1's
 * `unique_attribute_per_side_per_round` converts to.
 */
function heroBanRuleset(bansPerSide: number, uniqueRole: boolean): PickBanRuleset {
  const constraints = uniqueRole
    ? [{ type: "max_per_group", params: { max: 1, scope: "round", group: null } }]
    : [];
  const steps: PickBanRulesetStep[] = Array.from(
    { length: Math.max(0, bansPerSide) * 2 },
    (_, index) => ({
      id: `ban${index + 1}`,
      action: "ban",
      actors: index % 2 === 0 ? "first" : "second",
      count: 1,
      min: null,
      blind: false,
      target: null,
      lifetime: 1,
      timer_seconds: null,
      on_timeout: null,
      dispute: { enabled: false, max: 0 },
      eligible: {},
      constraints
    })
  );
  const base = emptyRuleset("hero");
  return { ...base, phases: [{ ...base.phases[0], steps }] };
}

/** Bans each side takes in a hero round, when hero bans are enabled. */
function heroBansPerSide(ruleset: PickBanRuleset): number {
  return Math.ceil((ruleset.phases[0]?.steps.length ?? 0) / 2);
}

/** Whether the hero rules carry the one-per-role constraint. */
function heroUniqueRole(ruleset: PickBanRuleset): boolean {
  return (ruleset.phases[0]?.steps ?? []).some((step) =>
    step.constraints.some((constraint) => constraint.type === "max_per_group")
  );
}

/**
 * A room's starting rules: an empty map pool on the bracket generator, no hero
 * bans.
 *
 * The generator is the right default here and nowhere else — the server builds
 * the step list from the pool and the series length, and a scrim knows its
 * `best_of` exactly, so the generated order is the real order rather than the
 * preview it is for a tournament-wide config.
 */
export function emptyScrimPoolDraft(): ScrimPoolDraft {
  return { map: emptyPickBanDraft("map"), hero: null };
}

/** Every rejection the two drafts carry, tagged with the kind that produced it. */
export function validateScrimPoolDraft(
  pool: ScrimPoolDraft
): { kind: "map" | "hero"; issue: PickBanValidationIssue }[] {
  const issues = validatePickBanDraft(pool.map).map((issue) => ({ kind: "map" as const, issue }));
  if (pool.hero == null) return issues;
  return [
    ...issues,
    ...validatePickBanDraft(pool.hero).map((issue) => ({ kind: "hero" as const, issue }))
  ];
}

/** One selectable map or hero. */
interface ItemOption {
  id: number;
  name: string;
}

/**
 * Search-and-toggle catalogue picker.
 *
 * Deliberately thinner than the organizer's grid picker: a scrim pool is chosen
 * once, in a dialog, by someone who already knows the names — art tiles, group
 * filter pills and select-all controls would cost more here than they buy.
 */
function ItemPicker({
  label,
  hint,
  searchPlaceholder,
  emptyLabel,
  loadingLabel,
  countLabel,
  isLoading,
  options,
  selectedIds,
  onToggle
}: Readonly<{
  label: string;
  hint: string;
  searchPlaceholder: string;
  emptyLabel: string;
  loadingLabel: string;
  countLabel: string;
  isLoading: boolean;
  options: ItemOption[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}>) {
  const ids = useId();
  const [query, setQuery] = useState("");
  const visible = useMemo(
    () =>
      query.trim() === ""
        ? options
        : options.filter((option) => matchesItemName(option.name, query)),
    [options, query]
  );

  return (
    <Field>
      <FieldLabel htmlFor={`${ids}-search`}>{label}</FieldLabel>
      <Input
        id={`${ids}-search`}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={searchPlaceholder}
        aria-describedby={`${ids}-hint`}
      />
      {isLoading ? (
        <p className="text-muted-foreground flex items-center gap-2 text-xs">
          <Spinner className="size-3.5" />
          {loadingLabel}
        </p>
      ) : visible.length === 0 ? (
        <p className="text-muted-foreground text-xs">{emptyLabel}</p>
      ) : (
        <div className="flex max-h-64 flex-wrap gap-2 overflow-y-auto rounded-lg border p-2">
          {visible.map((option) => {
            const selected = selectedIds.includes(option.id);
            return (
              <Button
                key={option.id}
                type="button"
                size="sm"
                variant={selected ? "default" : "outline"}
                aria-pressed={selected}
                onClick={() => onToggle(option.id)}
                className={cn("h-8", selected && "font-semibold")}
              >
                {selected ? <Check aria-hidden className="size-3.5" /> : null}
                {option.name}
              </Button>
            );
          })}
        </div>
      )}
      <FieldDescription id={`${ids}-hint`}>
        {hint}
        {selectedIds.length > 0 ? (
          <Badge variant="secondary" className="ms-2 align-middle">
            {countLabel}
          </Badge>
        ) : null}
      </FieldDescription>
    </Field>
  );
}

export function ScrimPoolEditor({
  pool,
  disabled,
  onChange
}: Readonly<{
  pool: ScrimPoolDraft;
  disabled?: boolean;
  onChange: (next: ScrimPoolDraft) => void;
}>) {
  const t = useTranslations("scrims.pool");
  const ids = useId();

  const mapsQuery = useMapsCatalog({ withGamemode: true });
  // Only fetched once hero bans are switched on: a map-only room never pays for it.
  const heroesQuery = useHeroesCatalog({ enabled: pool.hero != null });

  const mapOptions = useMemo<ItemOption[]>(
    () =>
      (mapsQuery.data ?? [])
        // Off-rotation maps are not something a scrim vetoes; the organizer's
        // editor holds the same line.
        .filter((map) => map.in_competitive !== false)
        .map((map) => ({ id: map.id, name: map.name })),
    [mapsQuery.data]
  );
  const heroOptions = useMemo<ItemOption[]>(
    () => (heroesQuery.data ?? []).map((hero) => ({ id: hero.id, name: hero.name })),
    [heroesQuery.data]
  );

  const heroDraft = pool.hero;

  /** The step timer is one setting of the room, so it lands on both rulesets. */
  const setTimer = (seconds: number | null) =>
    onChange({
      map: { ...pool.map, ruleset: { ...pool.map.ruleset, timer_seconds: seconds } },
      hero:
        heroDraft == null
          ? null
          : { ...heroDraft, ruleset: { ...heroDraft.ruleset, timer_seconds: seconds } }
    });

  return (
    <FieldSet disabled={disabled}>
      <FieldGroup>
        <div>
          <FieldTitle className="text-sm">{t("mapSection")}</FieldTitle>
          <FieldDescription>{t("mapSectionHint")}</FieldDescription>
        </div>

        <ItemPicker
          label={t("mapsLabel")}
          hint={t("mapsHint")}
          searchPlaceholder={t("searchMaps")}
          emptyLabel={t("noMatches")}
          loadingLabel={t("loadingCatalogue")}
          countLabel={t("selectedCount", { count: pool.map.itemIds.length })}
          isLoading={mapsQuery.isPending}
          options={mapOptions}
          selectedIds={pool.map.itemIds}
          onToggle={(id) =>
            onChange({
              ...pool,
              map: {
                ...pool.map,
                itemIds: pool.map.itemIds.includes(id)
                  ? pool.map.itemIds.filter((existing) => existing !== id)
                  : [...pool.map.itemIds, id]
              }
            })
          }
        />

        <Field>
          <FieldLabel htmlFor={`${ids}-timer`}>{t("turnTimer")}</FieldLabel>
          <NumberInput
            id={`${ids}-timer`}
            className="w-32"
            integer
            min={5}
            max={600}
            value={pool.map.ruleset.timer_seconds}
            onValueChange={setTimer}
            placeholder={t("turnTimerPlaceholder")}
            aria-describedby={`${ids}-timer-hint`}
          />
          <FieldDescription id={`${ids}-timer-hint`}>{t("turnTimerHint")}</FieldDescription>
        </Field>

        <Field orientation="horizontal">
          <Switch
            id={`${ids}-hero`}
            aria-describedby={`${ids}-hero-hint`}
            checked={heroDraft != null}
            onCheckedChange={(checked) =>
              onChange({
                ...pool,
                hero: checked
                  ? {
                      ...emptyPickBanDraft("hero"),
                      ruleset: {
                        ...heroBanRuleset(DEFAULT_HERO_BANS_PER_SIDE, false),
                        timer_seconds: pool.map.ruleset.timer_seconds
                      }
                    }
                  : null
              })
            }
          />
          <FieldContent>
            <FieldLabel htmlFor={`${ids}-hero`}>{t("heroToggle")}</FieldLabel>
            <FieldDescription id={`${ids}-hero-hint`}>{t("heroToggleHint")}</FieldDescription>
          </FieldContent>
        </Field>

        {heroDraft != null ? (
          <>
            <ItemPicker
              label={t("heroesLabel")}
              hint={t("heroesHint")}
              searchPlaceholder={t("searchHeroes")}
              emptyLabel={t("noMatches")}
              loadingLabel={t("loadingCatalogue")}
              countLabel={t("selectedCount", { count: heroDraft.itemIds.length })}
              isLoading={heroesQuery.isPending}
              options={heroOptions}
              selectedIds={heroDraft.itemIds}
              onToggle={(id) =>
                onChange({
                  ...pool,
                  hero: {
                    ...heroDraft,
                    itemIds: heroDraft.itemIds.includes(id)
                      ? heroDraft.itemIds.filter((existing) => existing !== id)
                      : [...heroDraft.itemIds, id]
                  }
                })
              }
            />

            <Field>
              <FieldLabel htmlFor={`${ids}-hero-bans`}>{t("heroBans")}</FieldLabel>
              <NumberInput
                id={`${ids}-hero-bans`}
                className="w-24"
                integer
                min={1}
                max={MAX_HERO_BANS_PER_SIDE}
                value={heroBansPerSide(heroDraft.ruleset)}
                onValueChange={(value) =>
                  onChange({
                    ...pool,
                    hero: {
                      ...heroDraft,
                      ruleset: {
                        ...heroBanRuleset(
                          value ?? DEFAULT_HERO_BANS_PER_SIDE,
                          heroUniqueRole(heroDraft.ruleset)
                        ),
                        timer_seconds: heroDraft.ruleset.timer_seconds
                      }
                    }
                  })
                }
                aria-describedby={`${ids}-hero-bans-hint`}
              />
              <FieldDescription id={`${ids}-hero-bans-hint`}>{t("heroBansHint")}</FieldDescription>
            </Field>

            <Field orientation="horizontal">
              <Switch
                id={`${ids}-hero-role`}
                aria-describedby={`${ids}-hero-role-hint`}
                checked={heroUniqueRole(heroDraft.ruleset)}
                onCheckedChange={(checked) =>
                  onChange({
                    ...pool,
                    hero: {
                      ...heroDraft,
                      ruleset: {
                        ...heroBanRuleset(heroBansPerSide(heroDraft.ruleset), checked),
                        timer_seconds: heroDraft.ruleset.timer_seconds
                      }
                    }
                  })
                }
              />
              <FieldContent>
                <FieldLabel htmlFor={`${ids}-hero-role`}>{t("uniqueRole")}</FieldLabel>
                <FieldDescription id={`${ids}-hero-role-hint`}>
                  {t("uniqueRoleHint")}
                </FieldDescription>
              </FieldContent>
            </Field>
          </>
        ) : null}
      </FieldGroup>
    </FieldSet>
  );
}
