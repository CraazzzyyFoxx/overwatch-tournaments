"use client";

import { isServer, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import AuthBootstrap from "@/components/auth/AuthBootstrap";
import WorkspaceBootstrap from "@/components/WorkspaceBootstrap";

function makeQueryClient() {
  return new QueryClient({
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
      <LanguageProvider>
        {children}
      </LanguageProvider>
    </QueryClientProvider>
  );
}
