"use client";

import { useQuery } from "@tanstack/react-query";
import type { OAuthProviderAvailability } from "@/types/auth.types";

const OAUTH_PROVIDERS_QUERY_KEY = ["auth", "oauth-providers"] as const;

async function fetchOAuthProviders(): Promise<OAuthProviderAvailability[]> {
  const response = await fetch("/api/v1/auth/providers", {
    method: "GET",
    cache: "no-store"
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload && typeof payload.detail === "string" ? payload.detail : "Failed to load OAuth providers";
    throw new Error(detail);
  }

  return response.json();
}

export function useOAuthProviders() {
  return useQuery({
    queryKey: OAUTH_PROVIDERS_QUERY_KEY,
    queryFn: fetchOAuthProviders,
    retry: false,
    staleTime: 60 * 1000
  });
}

