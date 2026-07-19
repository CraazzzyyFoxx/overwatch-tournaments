"use client";

import React from "react";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

export default function TournamentShellError() {
  const router = useRouter();
  const t = useTranslations();

  return (
    <div className="aqt-tn">
      <div
        role="alert"
        className="relative overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-6 py-14 text-center"
      >
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-0.5 bg-[color:var(--aqt-teal)]"
        />
        <p className="font-onest text-xl font-semibold text-[color:var(--aqt-fg)]">
          {t("common.loadError")}
        </p>
        <Button className="mt-5" onClick={() => router.refresh()}>
          <RefreshCw aria-hidden />
          {t("common.retry")}
        </Button>
      </div>
    </div>
  );
}
