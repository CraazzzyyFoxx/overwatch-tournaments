"use client";

import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { invalidProps, SettingGroup, settingHintId, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { FileButton } from "@/components/ui/file-button";
import { Input } from "@/components/ui/input";
import { revalidateUser } from "@/app/actions/users";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import meService from "@/services/me.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";

import { LinkedAccountsGroup } from "./LinkedAccountsGroup";

const AVATAR_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";
const AVATAR_MB = Math.round(MAX_AVATAR_BYTES / (1024 * 1024));

// The account-name rule, mirroring `normalize_username` in identity-service
// `schemas/auth.py`: NFKC, trimmed, 3-32 characters (code points, as Python
// counts them) of letters and digits in any script plus `_`, `.` and `-`
// (Python's Unicode `\w` is letters, numbers and `_`).
const USERNAME_MIN = 3;
const USERNAME_MAX = 32;
const USERNAME_RE = /^[\p{L}\p{N}_.-]+$/u;

export default function MyAccountSection() {
  const t = useTranslations("accountSettings");
  const user = useAuthProfileStore((s) => s.user);
  const fetchMe = useAuthProfileStore((s) => s.fetchMe);
  const { canUseCapability } = usePermissions();
  const canAvatar = canUseCapability("account.avatar");
  const canRename = canUseCapability("account.rename");

  const currentName = user?.username ?? "";
  const [name, setName] = useState(currentName);
  // The client check speaks once the reader leaves the field or tries to save,
  // then follows the value, so it clears as they fix it.
  const [touched, setTouched] = useState(false);
  // The server's refusal (a taken name), cleared by the next edit.
  const [refusal, setRefusal] = useState<string>();
  // Re-seed the field when the profile's name changes (load, save, refetch).
  const [seededName, setSeededName] = useState(currentName);
  if (seededName !== currentName) {
    setSeededName(currentName);
    setName(currentName);
    setTouched(false);
    setRefusal(undefined);
  }

  const normalized = name.normalize("NFKC").trim();
  const length = [...normalized].length;
  const changed = normalized !== currentName;
  const issue =
    length < USERNAME_MIN || length > USERNAME_MAX
      ? t("name.errors.length", { min: USERNAME_MIN, max: USERNAME_MAX })
      : USERNAME_RE.test(normalized)
        ? undefined
        : t("name.errors.chars");
  const nameError = refusal ?? (touched && changed ? issue : undefined);

  // Avatar failures surface via the global MutationCache.onError toast (see
  // providers.tsx), so these only need to refresh the profile on success.
  const avatarUpload = useMutation({
    mutationFn: (file: File) => meService.setAvatar(file),
    onSuccess: () => {
      void revalidateUser();
      fetchMe({ force: true });
    }
  });
  const avatarDelete = useMutation({
    mutationFn: () => meService.deleteAvatar(),
    onSuccess: () => {
      void revalidateUser();
      fetchMe({ force: true });
    }
  });
  const rename = useMutation({
    mutationFn: (username: string) => meService.updateUsername(username),
    // A refusal belongs under the field it is about, not in a toast.
    meta: { suppressErrorToast: true },
    onSuccess: () => {
      // identity drops the cached identity on rename and tells the gateway, so the next request already
      // carries the new name; the access token itself holds no name to re-issue.
      fetchMe({ force: true });
      notify.success(t("name.saved"));
    },
    // identity-svc answers a taken name with an English 400 (`update_me`); say it in the reader's language.
    onError: (error) =>
      setRefusal(
        error instanceof ApiError && error.status === 400
          ? t("name.errors.taken")
          : getApiErrorMessage(error, t("name.errors.failed"))
      )
  });

  const canSave = canRename && changed && !issue && !rename.isPending;
  const submitName = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (canSave) rename.mutate(normalized);
  };

  const hasAvatar = Boolean(user?.avatarUrl);
  const avatarBusy = avatarUpload.isPending || avatarDelete.isPending;

  return (
    <div className="space-y-6">
      <SettingGroup id="account-identity" level={4} title={t("identity.title")}>
        <SettingRow
          htmlFor="account-username"
          stacked
          label={t("name.label")}
          hint={canRename ? t("name.hint") : t("name.disabled")}
          count={{ value: length, max: USERNAME_MAX }}
          error={nameError}
        >
          <form className="flex w-full gap-2" onSubmit={submitName}>
            <Input
              id="account-username"
              className="min-w-0 flex-1"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setRefusal(undefined);
              }}
              onBlur={() => setTouched(true)}
              // A disabled submit blocks implicit submission, so Enter on an
              // invalid name would otherwise say nothing.
              onKeyDown={(event) => {
                if (event.key === "Enter") setTouched(true);
              }}
              maxLength={USERNAME_MAX}
              autoComplete="nickname"
              spellCheck={false}
              disabled={!canRename || rename.isPending}
              aria-describedby={settingHintId("account-username")}
              {...invalidProps("account-username", nameError)}
            />
            <Button type="submit" disabled={!canSave}>
              {t("name.save")}
            </Button>
          </form>
        </SettingRow>

        <SettingRow
          label={t("avatar.title")}
          hint={canAvatar ? t("avatar.hint", { mb: AVATAR_MB }) : t("avatar.disabled")}
        >
          <div className="flex items-center gap-3">
            <EditableAvatar
              src={user?.avatarUrl}
              name={user?.username}
              size={56}
              editable={canAvatar}
              busy={avatarBusy}
              accept={AVATAR_ACCEPT}
              onSelectFile={(file) => avatarUpload.mutate(file)}
              maxSizeBytes={MAX_AVATAR_BYTES}
              onError={(message) => notify.error(message)}
              labels={{
                change: t("avatar.change"),
                upload: t("avatar.upload"),
                edit: t("avatar.edit"),
                drop: t("avatar.drop"),
                unsupportedType: t("avatar.unsupported"),
                tooLarge: t("avatar.tooLarge", { mb: AVATAR_MB })
              }}
            />
            {canAvatar ? (
              <>
                <FileButton
                  variant="outline"
                  size="sm"
                  accept={AVATAR_ACCEPT}
                  disabled={avatarBusy}
                  onFiles={([file]) => {
                    // The picker's `accept` is a hint, not a filter: check what came back.
                    if (!AVATAR_ACCEPT.split(",").includes(file.type)) notify.error(t("avatar.unsupported"));
                    else if (file.size > MAX_AVATAR_BYTES) notify.error(t("avatar.tooLarge", { mb: AVATAR_MB }));
                    else avatarUpload.mutate(file);
                  }}
                >
                  {hasAvatar ? t("avatar.replace") : t("avatar.upload")}
                </FileButton>
                {hasAvatar ? (
                  <Button variant="ghost" size="sm" disabled={avatarBusy} onClick={() => avatarDelete.mutate()}>
                    {t("avatar.remove")}
                  </Button>
                ) : null}
              </>
            ) : null}
          </div>
        </SettingRow>
      </SettingGroup>

      <LinkedAccountsGroup />
    </div>
  );
}
