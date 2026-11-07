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
import WorkspaceBootstrap from "@/components/workspace/WorkspaceBootstrap";
import { useFlowErrorMessage } from "@/hooks/useFlowErrorNotifier";
import { ApiError, isDivisionGridRequired } from "@/lib/api/error";
import { notify } from "@/lib/notify";

/** The translated message of a known flow refusal; set by `Providers`, which sits under the intl provider. */
const flowMessageRef: { current: ((error: unknown) => string | null) | null } = { current: null };

/** A known flow refusal reads translated and actionable; any other error as the API reports it. */
function toastError(error: unknown) {
  const known = flowMessageRef.current?.(error);
  if (known) notify.error(known);
  else notify.apiError(error);
}

export function makeQueryClient() {
  return new QueryClient({
    // Surface API errors as toasts by default. Opt out per-call with
    // `meta: { suppressErrorToast: true }` (e.g. when a component shows its own UI).
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.suppressErrorToast) return;
        if (query.meta?.rendersGridRefusal && isDivisionGridRequired(error)) return;
        // 401s are owned by the token-refresh / login flow — don't spam logged-out users.
        if (error instanceof ApiError && error.status === 401) return;
        // Only the initial load (no cached data) — avoids spamming on background refetches.
        if (query.state.data === undefined) toastError(error);
      }
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.options.meta?.suppressErrorToast) return;
        toastError(error);
      }
    }),
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        refetchOnWindowFocus: true,
        // NEVER retry a gateway backpressure answer. 503 ("rpc unavailable")
        // means the gateway's per-queue in-flight cap shed the call because
        // that queue is already saturated, and 504 means the upstream worker
        // did not reply in time; TanStack's default (3 retries) turned every
        // such read into four requests inside ~7s — aimed at the one queue
        // that is already over capacity, and billed as four Sentry events
        // (OWT-TOURNAMENTS-23M). Nor a missing division grid: the refusal holds until an organizer publishes
        // one, so a retry only delays the notice. Everything else keeps the default.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && (error.status === 503 || error.status === 504)) &&
          !isDivisionGridRequired(error) &&
          failureCount < 3
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

export function Providers({ children }: Readonly<{ children: React.ReactNode }>) {
  const queryClient = getQueryClient();
  const flowMessage = useFlowErrorMessage();
  React.useEffect(() => {
    flowMessageRef.current = flowMessage;
  }, [flowMessage]);

  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap />
      <WorkspaceBootstrap />
      {children}
    </QueryClientProvider>
  );
}
