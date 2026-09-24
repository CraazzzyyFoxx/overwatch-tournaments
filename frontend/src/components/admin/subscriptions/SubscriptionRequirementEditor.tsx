"use client";

import { useId } from "react";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useRequirementDescription } from "@/components/admin/subscriptions/useRequirementDescription";
import { Label } from "@/components/ui/label";
import { SocialIcon } from "@/components/social/SocialIcon";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { PROVIDER_LABELS } from "@/lib/registration/subscription-requirement";
import type {
  SubscriptionProviderRequirement,
  SubscriptionRequirement
} from "@/types/registration.types";

/** Tier options per provider, in that provider's OWN vocabulary.
 *
 *  A shared numeric spinner would imply Boosty "Level 2" and Twitch "Tier 2"
 *  are comparable. They are not: each provider's threshold is evaluated only
 *  against its own verdict. Hence one message key per provider per rank rather
 *  than one parameterised "tier {n}" — the two vocabularies must stay separate
 *  in every locale, not merge into a shared word after translation.
 */
const TIER_OPTIONS = {
  boosty: [
    { rank: 1, labelKey: "tiers.boosty.any" },
    { rank: 2, labelKey: "tiers.boosty.level2" },
    { rank: 3, labelKey: "tiers.boosty.level3" }
  ],
  twitch: [
    { rank: 1, labelKey: "tiers.twitch.tier1" },
    { rank: 2, labelKey: "tiers.twitch.tier2" },
    { rank: 3, labelKey: "tiers.twitch.tier3" }
  ]
} as const;

/** A provider we have no vocabulary for still needs one selectable row. */
const GENERIC_TIER_OPTIONS = [{ rank: 1, labelKey: "tiers.anyTier" }] as const;

interface SubscriptionRequirementEditorProps {
  value: SubscriptionRequirement;
  onChange: (next: SubscriptionRequirement) => void;
  /** Providers configured AND enabled for this workspace. */
  availableProviders: string[];
  disabled?: boolean;
}

export default function SubscriptionRequirementEditor({
  value,
  onChange,
  availableProviders,
  disabled = false
}: Readonly<SubscriptionRequirementEditorProps>) {
  const t = useTranslations("subscriptionRequirement");
  const modeSelectId = useId();
  const description = useRequirementDescription(value);
  const rows = value.requirements ?? [];
  const mode = value.mode ?? "all";

  // A single requirement makes `any` and `all` the same answer, so offering the
  // choice invites a meaningless decision.
  const showModeSelector = rows.length > 1;

  const unavailable = rows
    .map((row) => row.provider)
    .filter((provider) => provider && !availableProviders.includes(provider));

  const update = (next: Partial<SubscriptionRequirement>) =>
    onChange({ mode, requirements: rows, ...next });

  const updateRow = (index: number, patch: Partial<SubscriptionProviderRequirement>) =>
    update({ requirements: rows.map((row, i) => (i === index ? { ...row, ...patch } : row)) });

  const remaining = availableProviders.filter(
    (provider) => !rows.some((row) => row.provider === provider)
  );

  return (
    <div className="space-y-3">
      {showModeSelector && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Label htmlFor={modeSelectId} className="text-muted-foreground">
            {t("matchLabel")}
          </Label>
          <Select
            value={mode}
            disabled={disabled}
            onValueChange={(value) => update({ mode: value as "any" | "all" })}
          >
            <SelectTrigger
              id={modeSelectId}
              // Content-sized: the translated mode labels overflow a fixed width.
              className="h-8 w-fit min-w-[190px] max-w-full text-sm"
              aria-label={t("modeAria")}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("modes.all")}</SelectItem>
              <SelectItem value="any">{t("modes.any")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {rows.length === 0 && <p className="text-xs text-muted-foreground">{t("emptyHint")}</p>}

      {rows.map((row, index) => {
        const tiers =
          TIER_OPTIONS[row.provider as keyof typeof TIER_OPTIONS] ?? GENERIC_TIER_OPTIONS;
        return (
          <div key={`${row.provider}-${index}`} className="flex flex-wrap items-center gap-2">
            <Select
              value={row.provider}
              disabled={disabled}
              onValueChange={(value) => updateRow(index, { provider: value })}
            >
              <SelectTrigger
                className="h-8 w-fit min-w-[140px] max-w-full text-sm"
                aria-label={t("providerAria")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* Keep the current value selectable even when unavailable, so
                    opening the form does not silently rewrite a saved rule. */}
                {[...new Set([row.provider, ...availableProviders])]
                  .filter(Boolean)
                  .map((provider) => (
                    <SelectItem key={provider} value={provider}>
                      <span className="flex items-center gap-2">
                        <SocialIcon provider={provider} size={14} decorative />
                        <span>{PROVIDER_LABELS[provider] ?? provider}</span>
                      </span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Select
              value={String(row.min_tier_rank ?? 1)}
              disabled={disabled}
              onValueChange={(value) => updateRow(index, { min_tier_rank: Number(value) })}
            >
              <SelectTrigger
                className="h-8 w-fit min-w-[170px] max-w-full text-sm"
                aria-label={t("minTierAria")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {tiers.map((tier) => (
                  <SelectItem key={tier.rank} value={String(tier.rank)}>
                    {t(tier.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => update({ requirements: rows.filter((_, i) => i !== index) })}
              aria-label={t("removeAria", {
                provider: PROVIDER_LABELS[row.provider] ?? row.provider
              })}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          </div>
        );
      })}

      {remaining.length > 0 && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() =>
            update({ requirements: [...rows, { provider: remaining[0], min_tier_rank: 1 }] })
          }
        >
          <Plus className="mr-1.5 size-3.5" aria-hidden />
          {t("addProvider")}
        </Button>
      )}

      {unavailable.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2.5">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
          <p className="max-w-prose text-xs text-warning">
            {t.rich("unconfiguredWarning", {
              count: unavailable.length,
              providers: unavailable.map((p) => PROVIDER_LABELS[p] ?? p).join(", "),
              em: (chunks) => <em>{chunks}</em>
            })}
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <p className="max-w-prose text-xs text-muted-foreground">
          {t.rich("summary", {
            rule: description,
            hl: (chunks) => <span className="font-medium">{chunks}</span>
          })}
        </p>
      )}
    </div>
  );
}
