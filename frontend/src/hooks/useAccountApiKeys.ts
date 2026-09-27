"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { parseApiError } from "@/lib/api/error";
import type {
  AccountApiKey,
  AccountApiKeyCreateInput,
  AccountApiKeyCreateResponse,
  QuotaLimitsPayload,
  QuotaUsage
} from "@/types/auth.types";
import type { PaginatedResponse } from "@/types/pagination.types";

const ACCOUNT_API_KEYS_QUERY_KEY = ["account", "api-keys"] as const;

export interface AccountApiKeyStatusCounts {
  total: number;
  active: number;
  expired: number;
  revoked: number;
}

export type AccountApiKeyListResult = PaginatedResponse<AccountApiKey> & {
  counts: AccountApiKeyStatusCounts;
  /**
   * Scope names the *caller* may grant, computed server-side from their own RBAC
   * in the queried workspace. A key can never exceed its owner's rights, so this
   * is the only legitimate source for the create dialog's checkbox list.
   */
  available_scopes: string[];
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

  const response = await fetch(`/bff/account/api-keys?${params.toString()}`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseError(response, "Failed to load API keys");
  }

  return response.json();
}

async function createApiKey(input: AccountApiKeyCreateInput): Promise<AccountApiKeyCreateResponse> {
  const response = await fetch("/bff/account/api-keys", {
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
  const response = await fetch(`/bff/account/api-keys/${input.id}`, {
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
  const response = await fetch(`/bff/account/api-keys/${id}`, {
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

/**
 * Spent-versus-ceiling for one key, in every scope it is charged against: its
 * own (`key`) and the workspace pool it shares with every other principal in
 * the tenant. Both are needed to read a 429, which names exactly one of them.
 *
 * `parseApiError` rather than the local `parseError` above: the quota answers
 * carry machine detail (`limit_name`, `limit`, `requested`) that a plain
 * `Error` would throw away.
 */
export async function fetchApiKeyQuota(apiKeyId: number): Promise<QuotaUsage> {
  const response = await fetch(`/bff/account/api-keys/${apiKeyId}/quota`, {
    method: "GET",
    cache: "no-store",
  });
  if (!response.ok) {
    throw await parseApiError(response);
  }
  return response.json();
}

export function useApiKeyQuota(apiKeyId: number | null) {
  return useQuery({
    queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, "quota", apiKeyId],
    queryFn: () => fetchApiKeyQuota(apiKeyId as number),
    enabled: apiKeyId !== null,
    // Counters move every minute; a cached panel would show a key as throttled
    // long after its window rolled over.
    staleTime: 0,
  });
}

export function useSetApiKeyQuota(workspaceId: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { id: number; limits: QuotaLimitsPayload }) => {
      const response = await fetch(`/bff/account/api-keys/${input.id}/quota`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limits: input.limits }),
      });
      if (!response.ok) {
        throw await parseApiError(response);
      }
      return (await response.json()) as QuotaLimitsPayload;
    },
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, "quota", variables.id],
      });
      await queryClient.invalidateQueries({
        queryKey: [...ACCOUNT_API_KEYS_QUERY_KEY, workspaceId],
      });
    },
  });
}
