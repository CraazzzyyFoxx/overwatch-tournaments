import { useTranslations } from "next-intl";

import type { RegistrationForm } from "@/types/registration.types";
import type { SocialAccount } from "@/types/user.types";
import AccountCombobox from "./AccountCombobox";
import VerifiedAccountSelect from "./VerifiedAccountSelect";
import SmurfTagsInput from "./SmurfTagsInput";
import FieldLabel from "./FieldLabel";
import { UserRound } from "lucide-react";

interface AccountStepProps {
  values: Record<string, string>;
  onUpdate: (key: string, value: string) => void;
  smurfTags: string[];
  onSmurfTagsChange: (tags: string[]) => void;
  onBuiltInValidationChange: (fieldKey: string, error: string | null) => void;
  form: RegistrationForm;
  battleTagSuggestions: string[];
  discordSuggestions: string[];
  twitchSuggestions: string[];
  mode?: "public" | "admin";
  displayName?: string;
  onDisplayNameChange?: (v: string) => void;
  /** Registrant's social accounts — drives the verified-account picker. */
  accounts?: readonly SocialAccount[];
  /** Per-field `require_verified` errors, computed by the parent. */
  verifiedErrors?: Record<string, string | null>;
}

export default function AccountStep({
  values,
  onUpdate,
  smurfTags,
  onSmurfTagsChange,
  onBuiltInValidationChange,
  form,
  battleTagSuggestions,
  discordSuggestions,
  twitchSuggestions,
  mode = "public",
  displayName,
  onDisplayNameChange,
  accounts = [],
  verifiedErrors = {},
}: AccountStepProps) {
  const t = useTranslations();
  const fields = form.built_in_fields;
  const showBattleTag = fields?.battle_tag?.enabled !== false;
  const showSmurfTags = fields?.smurf_tags?.enabled !== false;
  const showDiscord = fields?.discord_nick?.enabled !== false;
  const showTwitch = fields?.twitch_nick?.enabled !== false;
  // ``require_verified`` only applies to public self-registration (it gates on
  // the registrant's own OAuth-verified accounts); admin editing is unconstrained.
  const requireVerified = (key: string) =>
    mode === "public" && fields?.[key]?.require_verified === true;

  return (
    <div className="grid gap-4">
      <div className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-[color:var(--aqt-fg-muted)]">
          {mode === "admin" ? "Identity and Contact Handles" : t("registration.accounts.title")}
        </h3>
        <p className="text-xs leading-5 text-[color:var(--aqt-fg-dim)]">
          {mode === "admin"
            ? "Only the registration identity fields that matter in admin editing."
            : t("registration.accounts.desc")}
        </p>
      </div>

      {mode === "admin" && onDisplayNameChange && (
        <div className="space-y-1.5">
          <FieldLabel label="Display Name" icon={<UserRound className="size-3.5 opacity-50" />} />
          <input
            type="text"
            placeholder="Display name"
            value={displayName ?? ""}
            onChange={(e) => onDisplayNameChange(e.target.value)}
            className="h-9 w-full rounded-lg border border-[color:var(--aqt-border-2)] bg-white/3 px-3 text-sm text-[color:var(--aqt-fg)] placeholder-white/30 outline-none transition-colors focus:border-[color:var(--aqt-border-2)]"
          />
        </div>
      )}


      {showBattleTag && (
        requireVerified("battle_tag") ? (
          <VerifiedAccountSelect
            label={t("registration.accounts.battleTag")}
            provider="battlenet"
            accounts={accounts}
            value={values.battle_tag ?? ""}
            onChange={(v) => onUpdate("battle_tag", v)}
            required
            error={verifiedErrors.battle_tag}
          />
        ) : (
          <AccountCombobox
            label={t("registration.accounts.battleTag")}
            placeholder="Player#1234"
            value={values.battle_tag ?? ""}
            onChange={(v) => onUpdate("battle_tag", v)}
            suggestions={battleTagSuggestions}
            icon="/battlenet.svg"
            required={fields?.battle_tag?.required === true}
            fieldKey="battle_tag"
            config={fields?.battle_tag}
            onValidationChange={(error) => onBuiltInValidationChange("battle_tag", error)}
          />
        )
      )}

      {showSmurfTags && (
        <SmurfTagsInput
          tags={smurfTags}
          onChange={onSmurfTagsChange}
          suggestions={battleTagSuggestions.filter((t) => t !== (values.battle_tag ?? ""))}
          icon="/battlenet.svg"
          required={fields?.smurf_tags?.required === true}
          config={fields?.smurf_tags}
          onValidationChange={(error) => onBuiltInValidationChange("smurf_tags", error)}
        />
      )}

      {showDiscord && (
        requireVerified("discord_nick") ? (
          <VerifiedAccountSelect
            label={t("registration.accounts.discord")}
            provider="discord"
            accounts={accounts}
            value={values.discord_nick ?? ""}
            onChange={(v) => onUpdate("discord_nick", v)}
            required
            error={verifiedErrors.discord_nick}
          />
        ) : (
          <AccountCombobox
            label={t("registration.accounts.discord")}
            placeholder={t("registration.accounts.discordPlaceholder")}
            value={values.discord_nick ?? ""}
            onChange={(v) => onUpdate("discord_nick", v)}
            suggestions={discordSuggestions}
            icon="/discord-white.svg"
            required={fields?.discord_nick?.required === true}
            fieldKey="discord_nick"
            config={fields?.discord_nick}
            onValidationChange={(error) => onBuiltInValidationChange("discord_nick", error)}
          />
        )
      )}

      {showTwitch && (
        requireVerified("twitch_nick") ? (
          <VerifiedAccountSelect
            label={t("registration.accounts.twitch")}
            provider="twitch"
            accounts={accounts}
            value={values.twitch_nick ?? ""}
            onChange={(v) => onUpdate("twitch_nick", v)}
            required
            error={verifiedErrors.twitch_nick}
          />
        ) : (
          <AccountCombobox
            label={t("registration.accounts.twitch")}
            placeholder={t("registration.accounts.twitchPlaceholder")}
            value={values.twitch_nick ?? ""}
            onChange={(v) => onUpdate("twitch_nick", v)}
            suggestions={twitchSuggestions}
            icon="/twitch.png"
            required={fields?.twitch_nick?.required === true}
            fieldKey="twitch_nick"
            config={fields?.twitch_nick}
            onValidationChange={(error) => onBuiltInValidationChange("twitch_nick", error)}
          />
        )
      )}
    </div>
  );
}
