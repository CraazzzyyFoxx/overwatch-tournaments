"use client";

import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";
import { identityProvider } from "@/lib/forms/builtin-keys";
import type { SocialProvider } from "@/types/user.types";

import AccountCombobox from "../AccountCombobox";
import SubscriptionRow from "../SubscriptionRow";
import VerifiedAccountSelect from "../VerifiedAccountSelect";

/**
 * The provider an identity-shaped builtin asks for.
 *
 * `battle_tag` is its own builtin with its own grammar and column, but it is
 * still answered by a Battle.net handle, so the prefill and the suggestion list
 * treat it exactly like the `identity_*` keys. This is the ONE place that
 * mapping lives — it used to be four hand-copied branches in the wizard, one
 * per provider, and adding VK meant remembering all four.
 */
export function accountProviderFor(key: string): SocialProvider | null {
  if (key === "battle_tag") return "battlenet";
  return identityProvider(key) as SocialProvider | null;
}

/** Copy and iconography for the providers the UI has words for. VK and YouTube
 *  have none, so they fall back to the organizer's own field label. */
const PROVIDER_COPY = {
  discord: {
    label: "registration.accounts.discord",
    placeholder: "registration.accounts.discordPlaceholder",
    icon: "/discord-white.svg",
  },
  twitch: {
    label: "registration.accounts.twitch",
    placeholder: "registration.accounts.twitchPlaceholder",
    icon: "/twitch.png",
  },
  boosty: {
    label: "registration.accounts.boosty",
    placeholder: "registration.accounts.boostyPlaceholder",
    icon: "/boosty.svg",
  },
} as const;

/** Providers whose subscription standing is shown under the handle. */
const SUBSCRIPTION_LABELS: Record<string, string> = { twitch: "Twitch", boosty: "Boosty" };

export default function IdentityField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const provider = accountProviderFor(field.key);
  const current = typeof value === "string" ? value : "";
  const copy = provider ? PROVIDER_COPY[provider as keyof typeof PROVIDER_COPY] : undefined;
  const label = field.label || (copy ? t(copy.label) : field.key);

  // `require_verified` is enforced server-side; here it only decides WHICH
  // control to render, and only for the registrant — an organizer editing
  // somebody else's row was never constrained by it.
  const requireVerified = field.params.require_verified === true;

  const control =
    context.mode === "public" && requireVerified && provider ? (
      <VerifiedAccountSelect
        label={label}
        provider={provider}
        accounts={context.accounts}
        value={current}
        onChange={onChange}
        required={field.required}
        error={error}
      />
    ) : (
      <AccountCombobox
        label={label}
        placeholder={field.placeholder || (copy ? t(copy.placeholder) : "")}
        value={current}
        onChange={onChange}
        suggestions={context.accounts
          .filter((account) => account.provider === provider)
          .map((account) => account.username)}
        icon={copy?.icon}
        required={field.required}
        field={field}
        error={error}
      />
    );

  // Twitch has a real API and Boosty has none, so neither handle is what is
  // actually verified — the SUBSCRIPTION is, and this is where it reads.
  const subscriptionLabel = provider ? SUBSCRIPTION_LABELS[provider] : undefined;
  if (!subscriptionLabel || !provider) return control;
  return (
    <div className="grid gap-1.5">
      {control}
      <SubscriptionRow
        provider={provider}
        providerLabel={subscriptionLabel}
        subscription={context.subscription}
        onLinkAccounts={context.onLinkAccounts}
      />
    </div>
  );
}
