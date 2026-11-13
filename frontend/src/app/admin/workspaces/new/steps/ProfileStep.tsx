"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DEFAULT_WORKSPACE_TIMEZONE, getUtcOffsetLabel } from "@/lib/workspace/timezone";

import type { ProfileForm } from "../wizard-model";

/** The three community links, rendered identically: label, type, example. */
const LINK_FIELDS = [
  { key: "discord_url", labelKey: "links.discord", placeholder: "https://discord.gg/…" },
  { key: "twitch_url", labelKey: "links.twitch", placeholder: "https://twitch.tv/…" },
  { key: "boosty_url", labelKey: "links.boosty", placeholder: "https://boosty.to/…" }
] as const;

/** Step 2: what the community page says about the workspace. */
export function ProfileStep({
  value,
  onChange
}: Readonly<{ value: ProfileForm; onChange: (next: ProfileForm) => void }>) {
  const t = useTranslations("adminWorkspace.newWorkspace.profile");

  // Every IANA zone the runtime knows, with the saved value kept selectable
  // even when this runtime does not list it (as GeneralSection does).
  const timezoneOptions = useMemo(() => {
    let zones: string[];
    try {
      zones = Intl.supportedValuesOf("timeZone");
    } catch {
      zones = [DEFAULT_WORKSPACE_TIMEZONE, "UTC"];
    }
    return value.timezone && !zones.includes(value.timezone) ? [value.timezone, ...zones] : zones;
  }, [value.timezone]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Label htmlFor="workspace-tagline">{t("tagline")}</Label>
        <Input
          id="workspace-tagline"
          className="mt-1.5"
          maxLength={120}
          value={value.tagline}
          onChange={(event) => onChange({ ...value, tagline: event.target.value })}
        />
        <p className="mt-1 text-xs text-muted-foreground">{t("taglineHelp")}</p>
      </div>

      <div>
        <Label htmlFor="workspace-about">{t("about")}</Label>
        <Textarea
          id="workspace-about"
          className="mt-1.5 min-h-40 font-mono"
          maxLength={4000}
          value={value.about}
          onChange={(event) => onChange({ ...value, about: event.target.value })}
        />
        <p className="mt-1 text-xs text-muted-foreground">{t("aboutHelp")}</p>
      </div>

      {LINK_FIELDS.map(({ key, labelKey, placeholder }) => (
        <div key={key}>
          <Label htmlFor={`workspace-${key}`}>{t(labelKey)}</Label>
          <Input
            id={`workspace-${key}`}
            className="mt-1.5"
            type="url"
            inputMode="url"
            placeholder={placeholder}
            value={value[key]}
            onChange={(event) => onChange({ ...value, [key]: event.target.value })}
          />
        </div>
      ))}

      <div>
        <Label htmlFor="workspace-timezone">{t("timezone")}</Label>
        <Select
          value={value.timezone}
          onValueChange={(timezone) => onChange({ ...value, timezone })}
        >
          <SelectTrigger id="workspace-timezone" className="mt-1.5 w-full">
            <SelectValue placeholder={t("selectTimezone")} />
          </SelectTrigger>
          <SelectContent>
            {timezoneOptions.map((zone) => (
              <SelectItem key={zone} value={zone}>
                {zone} ({getUtcOffsetLabel(zone)})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="mt-1 text-xs text-muted-foreground">{t("timezoneHelp")}</p>
      </div>
    </div>
  );
}
