"use client";

import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";
import { identityMaxCount, identityProvider } from "@/lib/forms/builtin-keys";
import { getSocialProviderConfig } from "@/lib/social/providers";

import AccountCombobox from "../AccountCombobox";
import ExtraHandlesInput from "../ExtraHandlesInput";
import SubscriptionRow from "../SubscriptionRow";
import VerifiedAccountSelect from "../VerifiedAccountSelect";

/**
 * Copy and iconography per provider.
 *
 * A builtin field carries no label of its own — the server owns the question,
 * each client words it — so EVERY provider `IDENTITY_PROVIDERS` offers must have
 * an entry here or the registrant is asked a question titled `identity_vk`.
 * The i18n keys are derived from the provider name rather than listed twice:
 * `registration.accounts.<provider>` and `…<provider>Placeholder` exist for all
 * six, and a seventh provider added to the catalog gets its label from the same
 * rule the moment its two strings are translated. Only the brand icons are a
 * table, because only four of them are in `public/`.
 */
const PROVIDER_ICONS: Record<string, string> = {
  battlenet: "/battlenet.svg",
  discord: "/discord-white.svg",
  twitch: "/twitch.png",
  boosty: "/boosty.svg",
};

/** Providers whose subscription standing is shown under the handle. */
const SUBSCRIPTION_LABELS: Record<string, string> = { twitch: "Twitch", boosty: "Boosty" };

/** The handles an identity answer holds, primary first. A bare string is what a
 *  hand-written fixture or an older draft may carry; the answer this control
 *  commits is always a list. */
function handlesOf(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((handle): handle is string => typeof handle === "string");
  }
  return typeof value === "string" && value.trim() !== "" ? [value] : [];
}

/**
 * An `identity_<provider>` builtin: the registrant's handle for one provider.
 *
 * Several handles when the field's `max_count` allows them (five BattleTags by
 * default — smurfs are a normal Overwatch fact): the PRIMARY one is the
 * registration's public identity and gets the suggestion combobox or the
 * verified-account picker, the extras ride the same per-handle grammar in a
 * chip list below it. The answer is a list either way, primary first.
 */
export default function IdentityField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const provider = identityProvider(field.key);
  const label = field.label || (provider ? t(`registration.accounts.${provider}`) : field.key);

  const handles = handlesOf(value);
  const primary = handles[0] ?? "";
  const extras = handles.slice(1);
  const maxCount = provider ? identityMaxCount(provider, field.params) : 1;

  /** One writer for both controls: the answer is the primary handle followed by
   *  the extras, with blanks dropped — an emptied primary promotes the next. */
  const commit = (nextPrimary: string, nextExtras: readonly string[]) =>
    onChange([nextPrimary, ...nextExtras].filter((handle) => handle.trim() !== ""));

  // `require_verified` is enforced server-side, and only for providers that CAN
  // be verified; here it only decides WHICH control renders the primary handle,
  // and only for the registrant — an organizer editing somebody else's row was
  // never constrained by it.
  const requireVerified =
    field.params.require_verified === true &&
    provider !== null &&
    getSocialProviderConfig(provider).canBeVerified === true;

  const suggestions = context.accounts
    .filter((account) => account.provider === provider)
    .map((account) => account.username);

  const primaryControl =
    context.mode === "public" && requireVerified && provider ? (
      <VerifiedAccountSelect
        label={label}
        provider={provider}
        accounts={context.accounts}
        value={primary}
        onChange={(handle) => commit(handle, extras)}
        required={field.required}
        error={error}
      />
    ) : (
      <AccountCombobox
        label={label}
        placeholder={
          field.placeholder || (provider ? t(`registration.accounts.${provider}Placeholder`) : "")
        }
        value={primary}
        onChange={(handle) => commit(handle, extras)}
        suggestions={suggestions.filter((handle) => !extras.includes(handle))}
        icon={provider ? PROVIDER_ICONS[provider] : undefined}
        required={field.required}
        field={field}
        error={error}
      />
    );

  const control =
    maxCount > 1 ? (
      <div className="grid gap-1.5">
        {primaryControl}
        <ExtraHandlesInput
          handles={extras}
          onChange={(next) => commit(primary, next)}
          // One slot is the primary handle's.
          max={maxCount - 1}
          suggestions={suggestions.filter((handle) => handle !== primary)}
          icon={provider ? PROVIDER_ICONS[provider] : undefined}
          field={field}
        />
      </div>
    ) : (
      primaryControl
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
