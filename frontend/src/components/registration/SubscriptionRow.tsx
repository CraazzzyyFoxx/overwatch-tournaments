"use client";

import { useState } from "react";
import { ArrowRight, Link2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { SubscriptionProviderBadge } from "@/components/status/RegistrationBadges";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { getApiErrorMessage } from "@/lib/api/error";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import type { SubscriptionStatus } from "@/types/registration.types";
import { Spinner } from "@/components/ui/spinner";

interface SubscriptionRowProps {
  provider: string;
  providerLabel: string;
  subscription?: SubscriptionStatus | null;
  /** Opens profile settings so the user can link a Discord/Twitch account. */
  onLinkAccounts?: () => void;
  /** Redeem a challenge code for THIS provider. Only offered where the server
   *  says a code is accepted, and only at check-in — the signup form shows the
   *  verdict but never asks for a secret. */
  onRedeemCode?: (code: string, provider: string) => Promise<void>;
}

/**
 * One provider's subscription standing, rendered as an annotation of the account
 * field above it rather than a surface of its own.
 *
 * It used to be a bordered, filled card carrying the same border and background
 * tokens as an input, holding nothing but a 16px glyph — under the Twitch field
 * it read as a second, empty, broken control. Status belongs in the field's own
 * label/control/message rhythm, at message weight.
 *
 * The call to action is chosen from the verdict's `reason`, which is exactly why
 * the server sends it: a patron reading "no subscription" needs to know whether
 * to link Discord, reconnect Twitch, or paste a code. Renders nothing when the
 * tournament does not require this provider.
 */
export default function SubscriptionRow({
  provider,
  providerLabel,
  subscription,
  onLinkAccounts,
  onRedeemCode
}: Readonly<SubscriptionRowProps>) {
  const t = useTranslations();
  const tErrors = useTranslations("registrationTeams.errors");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!subscription?.required) return null;
  const verdict = subscription.verdicts?.[provider];
  if (!verdict) return null;

  const reason = verdict.reason ?? null;
  const showLinkDiscord = reason === "no_linked_discord_account" && Boolean(onLinkAccounts);
  const showReconnectTwitch = reason === "missing_scope" && Boolean(onLinkAccounts);
  // Two independent reasons a code is pointless here: the provider is already
  // satisfied, or this tournament does not verify by code at all — in which case
  // the server answers 400 and offering the input is a trap.
  const showCodeInput =
    Boolean(onRedeemCode) && verdict.state !== "active" && verdict.code_accepted === true;

  const submit = async () => {
    if (!onRedeemCode || !code.trim()) return;
    setPending(true);
    setError(null);
    try {
      await onRedeemCode(code.trim(), provider);
      setCode("");
    } catch (err) {
      // The refusal's `code` is what gets translated; the server's `msg` is only
      // the English default for a code this build does not know yet.
      setError(translateRegistrationTeamError(tErrors, err, getApiErrorMessage(err)));
    } finally {
      setPending(false);
    }
  };

  const controlId = `subscription-code-${provider}`;
  const errorId = `${controlId}-error`;
  const ctaLabel = showLinkDiscord
    ? t("common.subscription.linkDiscordCta")
    : showReconnectTwitch
      ? t("common.subscription.reconnectTwitchCta")
      : null;

  return (
    <div className="grid gap-1.5 text-xs">
      <SubscriptionProviderBadge
        provider={provider}
        providerLabel={providerLabel}
        verdict={verdict}
        className="justify-self-start"
      />

      {ctaLabel && (
        <Button
          type="button"
          variant="link"
          size="inline"
          onClick={onLinkAccounts}
          className="items-start justify-self-start gap-1.5 whitespace-normal text-left [&_svg]:size-3.5"
        >
          <Link2 className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {/* Arrow inside the text run so it trails the last word instead of
              drifting to the right edge once the label wraps. */}
          <span>
            {ctaLabel}
            <ArrowRight className="ml-1 inline align-[-0.1em]" aria-hidden />
          </span>
        </Button>
      )}

      {showCodeInput && (
        <div className="grid gap-1.5">
          {/* Deliberately not the uppercase/tracked field-label style: this
              labels a sub-control of the account field above, and matching that
              style made two labels of equal rank sit four lines apart. */}
          <label htmlFor={controlId} className="text-xs text-[color:var(--aqt-fg-dim)]">
            {t("common.subscription.codeLabel")}
          </label>
          <div className="flex gap-2">
            <Input
              id={controlId}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder={t("common.subscription.codePlaceholder")}
              autoComplete="off"
              disabled={pending}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? errorId : undefined}
            />
            <Button
              type="button"
              variant="accent"
              onClick={submit}
              disabled={pending || !code.trim()}
              className="shrink-0"
            >
              {pending && <Spinner className="size-3.5" />}
              {t("common.subscription.codeSubmit")}
            </Button>
          </div>
          <FieldError id={errorId} role="alert" size="sm">
            {error}
          </FieldError>
        </div>
      )}
    </div>
  );
}
