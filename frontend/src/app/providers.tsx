"use client";

import {
  isServer,
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider
} from "@tanstack/react-query";
import React from "react";

import AuthBootstrap from "@/components/auth/AuthBootstrap";
import WorkspaceBootstrap from "@/components/WorkspaceBootstrap";
import { ApiError } from "@/lib/api-error";
import { notify } from "@/lib/notify";

function makeQueryClient() {
  return new QueryClient({
    // Surface API errors as toasts by default. Opt out per-call with
    // `meta: { suppressErrorToast: true }` (e.g. when a component shows its own UI).
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.suppressErrorToast) return;
        // 401s are owned by the token-refresh / login flow — don't spam logged-out users.
        if (error instanceof ApiError && error.status === 401) return;
        // Only the initial load (no cached data) — avoids spamming on background refetches.
        if (query.state.data === undefined) notify.apiError(error);
      }
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.options.meta?.suppressErrorToast) return;
        notify.apiError(error);
      }
    }),
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        refetchOnWindowFocus: true
      }
    }
  });
}

let browserQueryClient: QueryClient | undefined = undefined;

function getQueryClient() {
  if (isServer) {
    return makeQueryClient();
  }
  if (!browserQueryClient) browserQueryClient = makeQueryClient();
  return browserQueryClient;
}

import { LanguageProvider } from "@/i18n/LanguageContext";

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap />
      <WorkspaceBootstrap />
      <LanguageProvider>{children}</LanguageProvider>
    </QueryClientProvider>
  );
}
