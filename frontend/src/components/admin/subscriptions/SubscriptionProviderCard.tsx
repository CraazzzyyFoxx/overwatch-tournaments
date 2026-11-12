"use client";

import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DiscordRoleSelect } from "@/components/discord/DiscordRoleSelect";
import { DiscordServerStatus } from "@/components/discord/DiscordServerStatus";
import { cn } from "@/lib/utils";
import { PROVIDER_LABELS } from "@/lib/registration/subscription-requirement";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  SubscriptionCodeUpsert,
  SubscriptionProviderConfigRead,
  SubscriptionProviderConfigUpsert,
  SubscriptionRoleTier,
  VerificationMethod,
} from "@/types/registration.types";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";

interface MethodOption {
  value: VerificationMethod;
  labelKey: string;
  descriptionKey: string;
}

/** The "live" mechanism in each provider's OWN vocabulary.
 *
 *  A Discord role and a Twitch subscription are not the same object, and one
 *  shared phrase would describe neither: the Boosty path reads roles a foreign
 *  bot assigns in your guild, the Twitch path queries Twitch itself. Hence one
 *  message key per provider rather than a parameterised "read from {provider}"
 *  — the two vocabularies must stay separate in every locale.
 *
 *  Keys, not literals: a module constant cannot call the translation hook, so
 *  the component resolves these with `t(...)` at render time.
 */
const LIVE_METHOD_KEYS = {
  boosty: {
    labelKey: "methods.live.boosty.label",
    descriptionKey: "methods.live.boosty.description",
  },
  twitch: {
    labelKey: "methods.live.twitch.label",
    descriptionKey: "methods.live.twitch.description",
  },
} as const;

/** A provider we have no vocabulary for still needs the live option offered. */
const GENERIC_LIVE_KEYS = {
  labelKey: "methods.live.generic.label",
  descriptionKey: "methods.live.generic.description",
} as const;

/** Provider-independent: a pasted secret is a pasted secret everywhere, and
 *  "either" is a composition of the two mechanisms rather than a mechanism. */
const CODE_AND_EITHER = [
  {
    value: "code",
    labelKey: "methods.code.label",
    descriptionKey: "methods.code.description",
  },
  {
    value: "any",
    labelKey: "methods.any.label",
    descriptionKey: "methods.any.description",
  },
] as const satisfies readonly MethodOption[];

/** One provider's unsaved edits, as the request that would store them. */
export interface ProviderDraft {
  label: string;
  payload: SubscriptionProviderConfigUpsert;
  /** Two tiers on one role: the server rejects it, so saving is refused here. */
  blocked: boolean;
}

interface SubscriptionProvidersCardProps {
  workspaceId: number;
  /** Bumped by the section after a save or a discard: every editor restarts from what is stored. */
  resetKey: number;
  /** A provider's draft while it differs from what is stored, `null` once it does not. */
  onDraftChange: (provider: string, draft: ProviderDraft | null) => void;
}

/**
 * The providers half of the subscriptions section: one settings group per
 * provider. It saves nothing itself: each editor reports its draft, and the
 * section's one `SaveBar` stores every draft together with the workspace rule.
 */
export default function SubscriptionProvidersCard({
  workspaceId,
  resetKey,
  onDraftChange,
}: Readonly<SubscriptionProvidersCardProps>) {
  const t = useTranslations("subscriptionProviders");

  const query = useQuery({
    queryKey: workspaceQueryKeys.subscriptionProviders(workspaceId),
    queryFn: () => balancerAdminService.listSubscriptionProviders(workspaceId),
    refetchOnWindowFocus: false,
  });

  if (query.isError) {
    return (
      <PageStateCard state="error" title={t("loadError")} onAction={() => void query.refetch()} />
    );
  }

  if (query.isLoading || !query.data) {
    // Two provider groups of label/control rows. The provider names are not
    // known until the configs land, so the bare card stands in for `SettingGroup`.
    return [0, 1].map((group) => (
      <Card key={group} aria-busy="true">
        <div className="px-5 py-3">
          <Skeleton className="h-5 w-24" />
        </div>
        <div className="@container flex flex-col gap-6 border-t border-border px-5 py-3">
          {[0, 1, 2].map((row) => (
            <div key={row} className="grid gap-2 @xl:grid-cols-2 @xl:items-center @xl:gap-6">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      </Card>
    ));
  }

  const { configs, discord_guild_id } = query.data;
  return configs.map((config) => (
    <ProviderEditor
      key={`${resetKey}:${config.provider}:${JSON.stringify(config)}`}
      workspaceId={workspaceId}
      config={config}
      discordGuildId={discord_guild_id ?? null}
      onDraftChange={onDraftChange}
    />
  ));
}

/** The editable role/code rows carry no server id, yet they can be removed from
 *  the middle of the list — and every role row hosts a `DiscordRoleSelect` with
 *  live UI state (open popover, manual-id mode, search text). Keyed by array
 *  index that state stays put and re-attaches to whichever row slid up into the
 *  removed slot, so each row gets a client-side id at creation time instead. */
let rowIdSeq = 0;
const nextRowId = () => {
  rowIdSeq += 1;
  return `row-${rowIdSeq}`;
};

type RoleTierRow = SubscriptionRoleTier & { rowId: string };
type CodeRow = SubscriptionCodeUpsert & { rowId: string };

function ProviderEditor({
  workspaceId,
  config,
  discordGuildId,
  onDraftChange,
}: Readonly<{
  workspaceId: number;
  config: SubscriptionProviderConfigRead;
  discordGuildId: string | null;
  onDraftChange: (provider: string, draft: ProviderDraft | null) => void;
}>) {
  const t = useTranslations("subscriptionProviders");
  const methodSelectId = useId();
  const label = PROVIDER_LABELS[config.provider] ?? config.provider;
  const isBoosty = config.provider === "boosty";

  const [enabled, setEnabled] = useState(config.enabled);
  const [broadcasterId, setBroadcasterId] = useState(config.broadcaster_id ?? "");
  const [broadcasterLogin, setBroadcasterLogin] = useState(config.broadcaster_login ?? "");
  const [roleTiers, setRoleTiers] = useState<RoleTierRow[]>(() =>
    config.role_tiers.map((tier) => ({ ...tier, rowId: nextRowId() }))
  );
  const [newCodes, setNewCodes] = useState<CodeRow[]>([]);
  const [method, setMethod] = useState<VerificationMethod>(
    config.verification_method === "live" || config.verification_method === "code"
      ? config.verification_method
      : "any"
  );

  const acceptsLive = method === "live" || method === "any";
  const acceptsCode = method === "code" || method === "any";

  const liveKeys =
    LIVE_METHOD_KEYS[config.provider as keyof typeof LIVE_METHOD_KEYS] ?? GENERIC_LIVE_KEYS;

  const methodOptions = [{ value: "live" as const, ...liveKeys }, ...CODE_AND_EITHER];
  const selectedMethod = methodOptions.find((option) => option.value === method);

  const payload: SubscriptionProviderConfigUpsert = {
    provider: config.provider,
    enabled,
    verification_method: method,
    // `rowId` is a client-side key, never part of the wire contract.
    ...(acceptsLive && isBoosty ? { role_tiers: roleTiers.map(({ rowId, ...tier }) => tier) } : {}),
    ...(acceptsLive && !isBoosty
      ? { broadcaster_id: broadcasterId.trim(), broadcaster_login: broadcasterLogin.trim() }
      : {}),
    ...(acceptsCode && newCodes.length > 0
      ? { codes: newCodes.map(({ rowId, ...code }) => code) }
      : {}),
  };
  // The first render's request is what is stored: any later difference is a draft.
  const serialized = JSON.stringify(payload);
  const [stored] = useState(serialized);
  const dirty = serialized !== stored;

  const duplicateRole =
    new Set(roleTiers.map((tier) => tier.role_id.trim()).filter(Boolean)).size !==
    roleTiers.filter((tier) => tier.role_id.trim()).length;

  useEffect(() => {
    onDraftChange(
      config.provider,
      dirty
        ? {
            label,
            // Parsed back from the string the effect keys on, so the object is
            // rebuilt only when the request actually changes.
            payload: JSON.parse(serialized) as SubscriptionProviderConfigUpsert,
            blocked: duplicateRole,
          }
        : null
    );
  }, [config.provider, dirty, duplicateRole, label, onDraftChange, serialized]);
  useEffect(() => () => onDraftChange(config.provider, null), [config.provider, onDraftChange]);

  const rolesMissing =
    acceptsLive && isBoosty && enabled && Boolean(discordGuildId) && roleTiers.length === 0;

  // Live Boosty verification without a guild resolves `unknown`, and `unknown`
  // fails open -- so the gate silently admits everybody. Say so on the screen.
  const guildMissing = acceptsLive && isBoosty && enabled && !discordGuildId;

  const codesMissing =
    method === "code" && enabled && config.codes.length === 0 && newCodes.length === 0;

  return (
    <SettingGroup id={`provider-${config.provider}`} title={label}>
      <SettingRow
        htmlFor={`enabled-${config.provider}`}
        label={t("enabled.label")}
        hint={t("enabled.hint")}
      >
        <Checkbox
          id={`enabled-${config.provider}`}
          checked={enabled}
          onCheckedChange={(checked) => setEnabled(checked === true)}
        />
      </SettingRow>

      {/* The chosen mechanism's consequence stays on screen. A dropdown that
          hid it would turn "Either" against "Challenge code" into a guess,
          which is what the radio list spelled out for free. */}
      <SettingRow
        htmlFor={methodSelectId}
        label={t("methodLabel")}
        hint={selectedMethod ? t(selectedMethod.descriptionKey) : undefined}
      >
        <Select value={method} onValueChange={(next) => setMethod(next as VerificationMethod)}>
          <SelectTrigger id={methodSelectId} className="w-full" aria-label={t("methodAria")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {methodOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {t(option.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingRow>

      {acceptsLive && isBoosty && (
        <>
          {/* The bound server's identity (name, icon, bot reachability); with
              none bound, the line that says so. The raw snowflake was never
              the useful half. */}
          <SettingRow label={t("guild.label")} hint={t("guild.hint")}>
            {discordGuildId ? (
              <DiscordServerStatus workspaceId={workspaceId} />
            ) : (
              <p
                className={cn(
                  "text-caption",
                  guildMissing ? "text-danger" : "text-muted-foreground"
                )}
              >
                {guildMissing ? t("guild.missing") : t("guild.unset")}
              </p>
            )}
          </SettingRow>

          <SettingRow label={t("roles.label")} stacked>
            <div className="w-full space-y-2">
              {roleTiers.map((tier, index) => (
                <div key={tier.rowId} className="flex flex-wrap items-center gap-2">
                  <DiscordRoleSelect
                    workspaceId={workspaceId}
                    value={tier.role_id}
                    onChange={(newRoleId) =>
                      setRoleTiers((rows) =>
                        rows.map((row, i) => (i === index ? { ...row, role_id: newRoleId } : row))
                      )
                    }
                    onRoleNameSelected={(roleName) =>
                      setRoleTiers((rows) =>
                        rows.map((row, i) =>
                          i === index && !row.tier_label ? { ...row, tier_label: roleName } : row
                        )
                      )
                    }
                    ariaLabel={t("roles.roleAria")}
                    // Wide enough that the role name survives once the two
                    // icon buttons take their 32px each; the row wraps rather
                    // than truncating the value to nothing.
                    className="min-w-56 flex-1"
                  />
                  <Input
                    type="number"
                    min={1}
                    value={tier.tier_rank}
                    onChange={(event) =>
                      setRoleTiers((rows) =>
                        rows.map((row, i) =>
                          i === index ? { ...row, tier_rank: Number(event.target.value) || 1 } : row
                        )
                      )
                    }
                    className="w-20"
                    aria-label={t("roles.tierRankAria")}
                  />
                  <Input
                    value={tier.tier_label ?? ""}
                    aria-label={t("roles.tierLabelAria")}
                    onChange={(event) =>
                      setRoleTiers((rows) =>
                        rows.map((row, i) =>
                          i === index ? { ...row, tier_label: event.target.value } : row
                        )
                      )
                    }
                    placeholder={t("roles.tierLabelPlaceholder")}
                    className="min-w-40 flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("roles.removeAria", { number: index + 1 })}
                    title={t("roles.removeAria", { number: index + 1 })}
                    onClick={() => setRoleTiers((rows) => rows.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setRoleTiers((rows) => [
                    ...rows,
                    { role_id: "", tier_rank: rows.length + 1, tier_label: "", rowId: nextRowId() }
                  ])
                }
              >
                {t("roles.add")}
              </Button>
            </div>
          </SettingRow>
        </>
      )}

      {acceptsLive && !isBoosty && (
        <>
          <SettingRow
            htmlFor={`bid-${config.provider}`}
            label={t("broadcaster.idLabel")}
            hint={t.rich("broadcaster.note", { em: (chunks) => <em>{chunks}</em> })}
          >
            <Input
              id={`bid-${config.provider}`}
              value={broadcasterId}
              onChange={(event) => setBroadcasterId(event.target.value)}
              placeholder="12345"
              inputMode="numeric"
              autoComplete="off"
              className="font-mono"
            />
          </SettingRow>
          <SettingRow htmlFor={`blogin-${config.provider}`} label={t("broadcaster.loginLabel")}>
            <Input
              id={`blogin-${config.provider}`}
              value={broadcasterLogin}
              onChange={(event) => setBroadcasterLogin(event.target.value)}
              placeholder={t("broadcaster.loginPlaceholder")}
              autoComplete="off"
            />
          </SettingRow>
        </>
      )}

      {acceptsCode && (
        <SettingRow
          label={t("codes.label")}
          stacked
          hint={
            <>
              {t("codes.hint")}
              {config.codes.length > 0 && (
                <>
                  {" "}
                  {t("codes.stored", {
                    codes: config.codes
                      .map(
                        (code) =>
                          code.tier_label || t("codes.tierFallback", { rank: code.tier_rank })
                      )
                      .join(", "),
                  })}
                </>
              )}
            </>
          }
        >
          <div className="w-full space-y-2">
            {newCodes.map((code, index) => (
              <div key={code.rowId} className="flex flex-wrap items-center gap-2">
                <Input
                  value={code.code ?? ""}
                  onChange={(event) =>
                    setNewCodes((rows) =>
                      rows.map((row, i) =>
                        i === index ? { ...row, code: event.target.value } : row
                      )
                    )
                  }
                  placeholder={t("codes.codePlaceholder")}
                  aria-label={t("codes.codeAria")}
                  autoComplete="off"
                  className="min-w-40 flex-1"
                />
                <Input
                  type="number"
                  min={1}
                  value={code.tier_rank}
                  onChange={(event) =>
                    setNewCodes((rows) =>
                      rows.map((row, i) =>
                        i === index ? { ...row, tier_rank: Number(event.target.value) || 1 } : row
                      )
                    )
                  }
                  className="w-20"
                  aria-label={t("codes.tierRankAria")}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t("codes.removeAria", { number: index + 1 })}
                  title={t("codes.removeAria", { number: index + 1 })}
                  onClick={() => setNewCodes((rows) => rows.filter((_, i) => i !== index))}
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setNewCodes((rows) => [...rows, { code: "", tier_rank: 1, rowId: nextRowId() }])
              }
            >
              {t("codes.addCode")}
            </Button>
            {newCodes.length > 0 && (
              <p className="text-caption text-warning">
                {t("codes.replaceWarning", { count: newCodes.length })}
              </p>
            )}
          </div>
        </SettingRow>
      )}

      {(duplicateRole || rolesMissing || codesMissing) && (
        <div className="space-y-1 py-4 last:pb-0">
          {duplicateRole && (
            <p className="max-w-prose text-caption text-danger">{t("warnings.duplicateRole")}</p>
          )}
          {rolesMissing && (
            <p className="max-w-prose text-caption text-warning">
              {t.rich("warnings.rolesMissing", { em: (chunks) => <em>{chunks}</em> })}
            </p>
          )}
          {codesMissing && (
            <p className="max-w-prose text-caption text-warning">
              {t.rich("warnings.codesMissing", { em: (chunks) => <em>{chunks}</em> })}
            </p>
          )}
        </div>
      )}
    </SettingGroup>
  );
}
