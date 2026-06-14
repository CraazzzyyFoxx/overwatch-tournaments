"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AccountApiKey, AccountApiKeyCreateResponse } from "@/types/auth.types";

export const ACCOUNT_API_KEYS_QUERY_KEY = ["account", "api-keys"] as const;

async function parseError(response: Response, fallback: string): Promise<Error> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  if (typeof detail === "string") {
    return new Error(detail);
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === "string") return new Error(first);
    if (typeof first?.msg === "string") return new Error(first.msg);
  }
  return new Error(fallback);
}

async function fetchApiKeys(workspaceId: number): Promise<AccountApiKey[]> {
  const response = await fetch(`/api/account/api-keys?workspace_id=${workspaceId}`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response, "Failed to load API keys");
  }

  return response.json();
}

async function createApiKey(input: {
  expires_at?: string | null;
  name: string;
  workspace_id: number;
}): Promise<AccountApiKeyCreateResponse> {
  const response = await fetch("/api/account/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    throw await parseError(response, "Failed to create API key");
  }

  return response.json();
}

async function renameApiKey(input: { id: number; name: string }): Promise<AccountApiKey> {
  const response = await fetch(`/api/account/api-keys/${input.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name }),
  });

  if (!response.ok) {
    throw await parseError(response, "Failed to rename API key");
  }

  return response.json();
}

async function revokeApiKey(id: number): Promise<void> {
  const response = await fetch(`/api/account/api-keys/${id}`, {
    method: "DELETE",
  });

  if (!response.ok && response.status !== 204) {
    throw await parseError(response, "Failed to revoke API key");
  }
}

export function useAccountApiKeys(workspaceId: number | null) {
  return useQuery({
    queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, workspaceId],
    queryFn: () => fetchApiKeys(workspaceId as number),
    enabled: workspaceId !== null,
    retry: false,
  });
}

export function useCreateAccountApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createApiKey,
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, variables.workspace_id],
      });
    },
  });
}

export function useRenameAccountApiKey(workspaceId: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: renameApiKey,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, workspaceId] });
    },
  });
}

export function useRevokeAccountApiKey(workspaceId: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: revokeApiKey,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, workspaceId] });
    },
  });
}
