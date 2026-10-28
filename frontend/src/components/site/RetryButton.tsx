"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/**
 * "Повторить" for a server-rendered block that failed to load: re-renders the
 * route's server components, which re-runs the failed read.
 */
export function RetryButton() {
  const t = useTranslations("site.state");
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={pending}
      aria-busy={pending}
      onClick={() => startTransition(() => router.refresh())}
      className="mt-2.5"
    >
      {pending ? <Spinner /> : <RefreshCw aria-hidden />}
      {t("retry")}
    </Button>
  );
}
