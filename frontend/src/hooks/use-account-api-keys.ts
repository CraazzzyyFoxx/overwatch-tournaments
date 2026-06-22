"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { AccountApiKey, AccountApiKeyCreateResponse } from "@/types/auth.types";
import type { PaginatedResponse } from "@/types/pagination.types";

export const ACCOUNT_API_KEYS_QUERY_KEY = ["account", "api-keys"] as const;

export interface AccountApiKeyStatusCounts {
  total: number;
  active: number;
  expired: number;
  revoked: number;
}

export type AccountApiKeyListResult = PaginatedResponse<AccountApiKey> & {
  counts: AccountApiKeyStatusCounts;
};

export interface FetchAccountApiKeysArgs {
  workspaceId: number;
  page: number;
  perPage: number;
  sort?: string;
  order?: string;
  search?: string;
}

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

export async function fetchAccountApiKeys(
  args: FetchAccountApiKeysArgs
): Promise<AccountApiKeyListResult> {
  const params = new URLSearchParams();
  params.set("workspace_id", String(args.workspaceId));
  params.set("page", String(args.page));
  params.set("per_page", String(args.perPage));
  if (args.sort) params.set("sort", args.sort);
  if (args.order) params.set("order", args.order);
  if (args.search) params.set("search", args.search);

  const response = await fetch(`/api/account/api-keys?${params.toString()}`, {
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
