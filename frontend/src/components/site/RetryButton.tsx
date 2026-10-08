"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { owtButton } from "./owt-button";

/**
 * "Повторить" for a server-rendered block that failed to load: re-renders the
 * route's server components, which re-runs the failed read.
 */
export function RetryButton({ className }: Readonly<{ className?: string }>) {
  const t = useTranslations("site.state");
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      type="button"
      disabled={pending}
      aria-busy={pending}
      onClick={() => startTransition(() => router.refresh())}
      className={cn(owtButton({ variant: "outline", size: "sm" }), "mt-2.5", className)}
    >
      <RefreshCw className={cn("size-3.5", pending && "motion-safe:animate-spin")} aria-hidden />
      {t("retry")}
    </button>
  );
}
