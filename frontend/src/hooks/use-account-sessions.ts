"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AccountSession } from "@/types/auth.types";

const ACCOUNT_SESSIONS_QUERY_KEY = ["account", "sessions"] as const;

async function fetchSessions(): Promise<AccountSession[]> {
  const response = await fetch("/api/account/sessions", {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload && typeof payload.detail === "string" ? payload.detail : "Failed to load sessions";
    throw new Error(detail);
  }

  return response.json();
}

async function revokeSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/account/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });

  if (!response.ok && response.status !== 204) {
    const payload = await response.json().catch(() => null);
    const detail = payload && typeof payload.detail === "string" ? payload.detail : "Failed to revoke session";
    throw new Error(detail);
  }
}

export function useAccountSessions() {
  return useQuery({
    queryKey: ACCOUNT_SESSIONS_QUERY_KEY,
    queryFn: fetchSessions,
    retry: false,
  });
}

export function useRevokeAccountSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: revokeSession,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ACCOUNT_SESSIONS_QUERY_KEY });
    },
  });
}
