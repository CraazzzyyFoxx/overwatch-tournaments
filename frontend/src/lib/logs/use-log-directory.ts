"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import {
  allowLogDirectoryRead,
  forgetLogDirectory,
  LogDirectoryError,
  pickLogDirectory,
  readLogDirectory,
  saveLogDirectory
} from "./browser-directory";

export function useLogDirectory() {
  const accountId = useAuthProfileStore((state) => state.user?.id);
  const queryClient = useQueryClient();
  const queryKey = ["local-log-directory", accountId] as const;
  // Local like the folder handle it drives: on another browser there is no folder to watch.
  const [autoUploadSetting, setAutoUpload] = useLocalStorageState(`aqt:log-auto-upload:${accountId ?? "anonymous"}`, false);
  const query = useQuery({
    queryKey,
    queryFn: async () => {
      if (accountId == null) throw new LogDirectoryError("account");
      const handle = await readLogDirectory(accountId);
      if (handle) await handle.queryPermission({ mode: "read" });
      return handle;
    },
    enabled: accountId != null,
    staleTime: Infinity,
    retry: false
  });

  function requireAccount(): number {
    if (accountId == null || useAuthProfileStore.getState().user?.id !== accountId) {
      throw new LogDirectoryError("account");
    }
    return accountId;
  }

  async function select() {
    const id = requireAccount();
    // Nothing asynchronous may precede the native picker on this click path.
    const handle = await pickLogDirectory();
    if (!handle) return null;
    requireAccount();
    await saveLogDirectory(id, handle);
    void queryClient.invalidateQueries({ queryKey, refetchType: "none" });
    queryClient.setQueryData(queryKey, handle);
    return handle;
  }

  async function access() {
    requireAccount();
    if (query.error) throw query.error;
    if (!query.isSuccess) throw new LogDirectoryError("storage");
    const handle = query.data;
    if (!handle) return select();
    await allowLogDirectoryRead(handle);
    requireAccount();
    return handle;
  }

  async function forget() {
    const id = requireAccount();
    await forgetLogDirectory(id);
    setAutoUpload(false);
    void queryClient.invalidateQueries({ queryKey, refetchType: "none" });
    queryClient.setQueryData(queryKey, null);
  }

  const handle = query.data ?? null;
  return {
    accountId,
    handle,
    isLoading: query.isLoading,
    error: query.error,
    autoUpload: accountId != null && handle != null && autoUploadSetting,
    setAutoUpload,
    select,
    access,
    forget
  };
}
