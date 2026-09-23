"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/usePermissions";
import meService from "@/services/me.service";
import { revalidateUser } from "@/app/actions/users";

import { SettingsGroup } from "./SettingsGroup";

export default function PrivacySection() {
  const t = useTranslations("accountSettings");
  const { canUseCapability } = usePermissions();
  const queryClient = useQueryClient();

  // Same query as the profile tab's linked accounts: the flag rides on the
  // social profile, so both tabs read and write one cache entry.
  const socialQuery = useQuery({
    queryKey: ["me", "social"],
    queryFn: () => meService.getSocialAccounts(),
    enabled: canUseCapability("account.social"),
  });
  // Only an explicit `false` is a veto: responses cached before the flag
  // existed omit it entirely, and the backend default is "allowed" — the same
  // rule the per-account row applies to `visible_global`.
  const streamVisible = socialQuery.data?.stream_visible !== false;

  // The endpoint answers with the refreshed user, so the switch state comes
  // straight from the server; revalidating busts the Next Data Cache so the
  // public pages follow at once. Failures surface via the global mutation toast.
  const setStreamVisibility = useMutation({
    mutationFn: (visible: boolean) => meService.setStreamVisibility(visible),
    onSuccess: (user) => {
      void revalidateUser(user.id);
      queryClient.setQueryData(["me", "social"], user);
    },
  });

  return (
    <SettingsGroup title={t("stream.title")}>
      <div className="flex items-start gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5">
        <div className="flex-1 space-y-1">
          <p id="stream-visibility-label" className="text-sm text-[color:var(--aqt-fg)]">
            {t("stream.toggleLabel")}
          </p>
          <p id="stream-visibility-desc" className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">
            {t("stream.toggleDesc")}
          </p>
        </div>
        <Switch
          checked={streamVisible}
          // Never let the switch act on a guess: without a loaded response
          // there is no current value to invert, and a wrong payload here
          // silently re-publishes a stream the user meant to hide.
          disabled={!socialQuery.data || setStreamVisibility.isPending}
          onCheckedChange={(next) => setStreamVisibility.mutate(next)}
          aria-labelledby="stream-visibility-label"
          aria-describedby="stream-visibility-desc"
        />
      </div>
      <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">{t("stream.footnote")}</p>
    </SettingsGroup>
  );
}
