"use client";

import { useEffect, useId } from "react";
import { Check, ShieldCheck, ExternalLink } from "lucide-react";
import type { SocialAccount, SocialProvider } from "@/types/user.types";

import { useTranslations } from "next-intl";
import { getSocialProviderConfig } from "@/lib/social/providers";
import { SocialIcon } from "@/components/social/SocialIcon";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import FieldLabel from "./FieldLabel";
import { fieldControlClass, fieldInvalidClass } from "./FormField";

interface VerifiedAccountSelectProps {
  label: string;
  provider: SocialProvider;
  /** All of the registrant's social accounts (filtered to verified internally). */
  accounts: readonly SocialAccount[];
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  error?: string | null;
}

/**
 * Identity field rendered as a picker constrained to the registrant's
 * OAuth-verified accounts for a provider. When none exist it surfaces a link to
 * the OAuth flow so the user can verify the account, and keeps the value empty
 * so the parent's `require_verified` validation blocks submission.
 */
export default function VerifiedAccountSelect({
  label,
  provider,
  accounts,
  value,
  onChange,
  required = false,
  error = null,
}: Readonly<VerifiedAccountSelectProps>) {
  const t = useTranslations();
  const controlId = useId();
  const errorId = `${controlId}-error`;
  const hintId = `${controlId}-hint`;
  const config = getSocialProviderConfig(provider);
  const verified = accounts.filter((a) => a.provider === provider && a.is_verified);
  const usernames = verified.map((a) => a.username);

  // Default to the (single) verified account when the current value isn't one
  // of them — the common case is exactly one linked account, so this is
  // zero-click. Kept in an effect so we don't mutate parent state during render.
  useEffect(() => {
    if (usernames.length > 0 && !usernames.includes(value)) {
      onChange(usernames[0]);
    }
    if (usernames.length === 0 && value) {
      onChange("");
    }
  }, [usernames.join(" "), value]);

  const iconEl = <SocialIcon provider={provider} size={14} className="opacity-60" />;

  if (verified.length === 0) {
    const next = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
    const connectHref = `/auth/${provider}/login?action=link&next=${encodeURIComponent(next)}`;
    return (
      <div className="space-y-2">
        <FieldLabel label={label} required={required} icon={iconEl} />
        <div className="rounded-lg border border-warning/30 bg-warning/5 p-3">
          <p className="text-xs text-warning">
            {t("registration.accounts.verifiedNone", { label })}
          </p>
          <a
            href={connectHref}
            className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2.5 py-1.5 text-xs font-medium text-[color:var(--aqt-fg)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            // `color-mix`, not a JS hex parse: `config.color` is an `--aqt-brand-*` token.
            style={{ borderColor: `color-mix(in srgb, ${config.color} 33%, transparent)` }}
          >
            <SocialIcon provider={provider} size={13} />
            {t("registration.accounts.verifiedLink", { label })}
            <ExternalLink className="size-3 opacity-60" aria-hidden />
          </a>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <FieldLabel label={label} htmlFor={controlId} required={required} icon={iconEl} />
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          id={controlId}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : hintId}
          className={cn(fieldControlClass, "h-9", error && fieldInvalidClass)}
        >
          <SelectValue placeholder={config.placeholder} />
        </SelectTrigger>
        <SelectContent>
          {verified.map((account) => (
            <SelectItem key={account.id} value={account.username}>
              <span className="flex items-center gap-2">
                <SocialIcon provider={provider} size={13} />
                <span className="truncate">{account.username}</span>
                <ShieldCheck
                  className="size-3.5 text-[color:var(--aqt-emerald)]"
                  aria-label={t("registration.accounts.verified")}
                />
                {value === account.username && <Check className="size-3.5 opacity-60" aria-hidden />}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p id={hintId} className="text-label text-[color:var(--aqt-fg-dim)]">
        {t("registration.accounts.verifiedHint")}
      </p>
      {error && <p id={errorId} className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
