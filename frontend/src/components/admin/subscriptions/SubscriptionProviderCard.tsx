"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, Save, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DiscordRoleSelect } from "@/components/discord/DiscordRoleSelect";
import { DiscordServerStatus } from "@/components/discord/DiscordServerStatus";
import { SocialIcon } from "@/components/social/SocialIcon";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { PROVIDER_LABELS } from "@/lib/registration/subscription-requirement";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  SubscriptionCodeUpsert,
  SubscriptionProviderConfigRead,
  SubscriptionRoleTier,
  VerificationMethod,
} from "@/types/registration.types";
import { Spinner } from "@/components/ui/spinner";

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

interface SubscriptionProvidersCardProps {
  workspaceId: number;
}

export default function SubscriptionProvidersCard({ workspaceId }: Readonly<SubscriptionProvidersCardProps>) {
  const t = useTranslations("subscriptionProviders");
  const queryClient = useQueryClient();
  const queryKey = ["subscription-providers", workspaceId] as const;

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => balancerAdminService.listSubscriptionProviders(workspaceId),
    refetchOnWindowFocus: false,
  });

  return (
    <Card className="border-border/60">
      <CardHeader className="p-4 pb-3">
        <CardTitle className="text-base font-semibold">{t("title")}</CardTitle>
        <CardDescription className="max-w-prose text-xs">{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-0">
        {workspaceId ? <DiscordServerStatus workspaceId={workspaceId} className="mb-2" /> : null}
        {isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Spinner className="size-3.5" />
            {t("loading")}
          </div>
        )}

        {data?.configs.map((config) => (
          <ProviderEditor
            key={`${config.provider}:${JSON.stringify(config)}`}
            workspaceId={workspaceId}
            config={config}
            discordGuildId={data.discord_guild_id ?? null}
            onSaved={() => queryClient.invalidateQueries({ queryKey })}
          />
        ))}
      </CardContent>
    </Card>
  );
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
  onSaved,
}: Readonly<{
  workspaceId: number;
  config: SubscriptionProviderConfigRead;
  discordGuildId: string | null;
  onSaved: () => void;
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

  const save = useMutation({
    mutationFn: () =>
      balancerAdminService.upsertSubscriptionProvider(workspaceId, {
        provider: config.provider,
        enabled,
        verification_method: method,
        // `rowId` is a client-side key, never part of the wire contract.
        ...(acceptsLive && isBoosty
          ? { role_tiers: roleTiers.map(({ rowId, ...tier }) => tier) }
          : {}),
        ...(acceptsLive && !isBoosty
          ? { broadcaster_id: broadcasterId.trim(), broadcaster_login: broadcasterLogin.trim() }
          : {}),
        ...(acceptsCode && newCodes.length > 0
          ? { codes: newCodes.map(({ rowId, ...code }) => code) }
          : {}),
      }),
    onSuccess: () => {
      notify.success(t("saved", { provider: label }));
      onSaved();
    },
    onError: (error: unknown) =>
      notify.error(
        error instanceof Error ? error.message : t("saveFailed", { provider: label })
      ),
  });

  const duplicateRole =
    new Set(roleTiers.map((tier) => tier.role_id.trim()).filter(Boolean)).size !==
    roleTiers.filter((tier) => tier.role_id.trim()).length;

  const rolesMissing =
    acceptsLive && isBoosty && enabled && Boolean(discordGuildId) && roleTiers.length === 0;

  // Live Boosty verification without a guild resolves `unknown`, and `unknown`
  // fails open -- so the gate silently admits everybody. Say so on the screen.
  const guildMissing = acceptsLive && isBoosty && enabled && !discordGuildId;

  const codesMissing =
    method === "code" && enabled && config.codes.length === 0 && newCodes.length === 0;

  return (
    <Card className="rounded-lg border-border/50 bg-muted/10 shadow-none">
      <CardHeader className="p-3 pb-2 flex flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`enabled-${config.provider}`}
            checked={enabled}
            onCheckedChange={(checked) => setEnabled(checked === true)}
          />
          <Label
            htmlFor={`enabled-${config.provider}`}
            className="flex cursor-pointer items-center gap-1.5 text-sm font-semibold"
          >
            <SocialIcon provider={config.provider} size={16} decorative />
            {label}
          </Label>
          <Badge tone={enabled ? "success" : "neutral"} className="text-xs uppercase font-mono">
            {enabled ? t("status.active") : t("status.disabled")}
          </Badge>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={save.isPending || duplicateRole}
          onClick={() => save.mutate()}
        >
          {save.isPending && (
            <Spinner className="mr-1.5 size-3.5" />
          )}
          {!save.isPending && <Save className="mr-1.5 size-3.5" aria-hidden />}
          {t("save")}
        </Button>
      </CardHeader>

      <CardContent className="p-3 pt-1 space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor={methodSelectId} className="text-xs font-medium text-muted-foreground">
            {t("methodLabel")}
          </Label>
          <Select value={method} onValueChange={(next) => setMethod(next as VerificationMethod)}>
            <SelectTrigger
              id={methodSelectId}
              className="h-8 w-full text-xs sm:max-w-xs"
              aria-label={t("methodAria")}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {methodOptions.map((option) => (
                <SelectItem key={option.value} value={option.value} className="text-xs">
                  {t(option.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* The chosen mechanism's consequence stays on screen. A dropdown that
              hid it would turn "Either" against "Challenge code" into a guess,
              which is what the radio list spelled out for free. */}
          {selectedMethod && (
            <p className="max-w-prose text-xs text-muted-foreground">
              {t(selectedMethod.descriptionKey)}
            </p>
          )}
        </div>

        {acceptsLive &&
          (isBoosty ? (
            <div className="space-y-3 pt-1">
              <div className="space-y-1">
                {/* The server's own identity is the status card above — name, icon,
                    bot reachability. This line only speaks up when there is nothing
                    to show; the raw snowflake was never the useful half. */}
                {!discordGuildId && (
                  <p
                    className={cn(
                      "text-xs",
                      guildMissing ? "font-medium text-destructive" : "text-muted-foreground"
                    )}
                  >
                    {guildMissing ? t("guild.missing") : t("guild.unset")}
                  </p>
                )}
                <p className="max-w-prose text-xs text-muted-foreground">{t("guild.hint")}</p>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs font-medium">{t("roles.label")}</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setRoleTiers((rows) => [
                        ...rows,
                        { role_id: "", tier_rank: rows.length + 1, tier_label: "", rowId: nextRowId() },
                      ])
                    }
                  >
                    <Plus className="mr-1.5 size-3.5" aria-hidden />
                    {t("roles.add")}
                  </Button>
                </div>

                {roleTiers.map((tier, index) => (
                  <div key={tier.rowId} className="flex flex-wrap items-center gap-2">
                    <DiscordRoleSelect
                      workspaceId={workspaceId}
                      value={tier.role_id}
                      onChange={(newRoleId) =>
                        setRoleTiers((rows) =>
                          rows.map((row, i) =>
                            i === index ? { ...row, role_id: newRoleId } : row
                          )
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
                      className="h-8 w-20"
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
                      className="h-8 min-w-40 flex-1"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={t("roles.removeAria", { number: index + 1 })}
                      onClick={() => setRoleTiers((rows) => rows.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 pt-1">
              <div className="space-y-1">
                <Label htmlFor={`bid-${config.provider}`} className="text-xs font-medium">
                  {t("broadcaster.idLabel")}
                </Label>
                <Input
                  id={`bid-${config.provider}`}
                  value={broadcasterId}
                  onChange={(event) => setBroadcasterId(event.target.value)}
                  placeholder="12345"
                  inputMode="numeric"
                  autoComplete="off"
                  className="h-8 font-mono"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`blogin-${config.provider}`} className="text-xs font-medium">
                  {t("broadcaster.loginLabel")}
                </Label>
                <Input
                  id={`blogin-${config.provider}`}
                  value={broadcasterLogin}
                  onChange={(event) => setBroadcasterLogin(event.target.value)}
                  placeholder={t("broadcaster.loginPlaceholder")}
                  autoComplete="off"
                  className="h-8"
                />
              </div>
              <p className="max-w-prose text-xs text-muted-foreground sm:col-span-2">
                {t.rich("broadcaster.note", { em: (chunks) => <em>{chunks}</em> })}
              </p>
            </div>
          ))}

        {acceptsCode && (
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs font-medium">{t("codes.label")}</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setNewCodes((rows) => [...rows, { code: "", tier_rank: 1, rowId: nextRowId() }])
                }
              >
                <Plus className="mr-1.5 size-3.5" aria-hidden />
                {t("codes.addCode")}
              </Button>
            </div>
            <p className="max-w-prose text-xs text-muted-foreground">
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
            </p>
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
                  className="h-8 min-w-40 flex-1"
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
                  className="h-8 w-20"
                  aria-label={t("codes.tierRankAria")}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t("codes.removeAria", { number: index + 1 })}
                  onClick={() => setNewCodes((rows) => rows.filter((_, i) => i !== index))}
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </div>
            ))}
            {newCodes.length > 0 && (
              <p className="text-xs text-warning">
                {t("codes.replaceWarning", { count: newCodes.length })}
              </p>
            )}
          </div>
        )}

        {duplicateRole && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-2.5">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            <p className="max-w-prose text-xs text-destructive">{t("warnings.duplicateRole")}</p>
          </div>
        )}

        {rolesMissing && (
          <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2.5">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
            <p className="max-w-prose text-xs text-warning">
              {t.rich("warnings.rolesMissing", { em: (chunks) => <em>{chunks}</em> })}
            </p>
          </div>
        )}

        {codesMissing && (
          <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2.5">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
            <p className="max-w-prose text-xs text-warning">
              {t.rich("warnings.codesMissing", { em: (chunks) => <em>{chunks}</em> })}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
