"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { TOOLBAR_BUTTON_CLASS } from "@/components/balancer/balancer-page-helpers";
import { getTournamentStatusMeta, displayStatus } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import type { BalancerTournamentSummary } from "@/types/balancer-admin.types";

type BalancerToolTopBarProps = {
  summary: BalancerTournamentSummary;
};

/**
 * Standalone top-bar of the balancer tool (D30) — the tool's entire shell.
 * Provides the portal hosts other balancer components rely on:
 * `#balancer-header-slot` (Run controls from PresetRunPanel, no fallback) and
 * `#balancer-presence-slot` (live viewer stack from BalancerPresenceStack).
 */
export function BalancerToolTopBar({ summary }: Readonly<BalancerToolTopBarProps>) {
  const t = useTranslations("balancerTool.topBar");
  const tStatus = useTranslations("common.statusBadge");
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("return");
  // Only trust internal paths from `?return=` (e.g. the creation wizard);
  // protocol-relative `//host` would be an open redirect — reject it too.
  const backHref =
    returnTo?.startsWith("/") && !returnTo.startsWith("//")
      ? returnTo
      : `/admin/tournaments/${summary.id}/teams/roster`;

  return (
    <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b border-border/50 bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/82 md:px-5">
      <Link
        href={backHref}
        className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        <span className="hidden sm:inline">{t("back")}</span>
      </Link>
      <Separator orientation="vertical" className="h-5" />
      <div className="flex min-w-0 shrink items-center gap-2">
        <span className="truncate text-sm font-medium">{summary.name}</span>
        <TournamentStatusPill status={getTournamentStatusMeta(displayStatus(summary)).variant} className="shrink-0">
          {tStatus(summary.status)}
        </TournamentStatusPill>
      </div>
      {/* Host for the live "viewing now" stack (filled by BalancerPresenceStack via portal). */}
      <div id="balancer-presence-slot" className="flex shrink-0 items-center empty:hidden" />
      {/* PresetRunPanel portals the Run controls here — this container must always exist (D30). */}
      <div id="balancer-header-slot" className="ml-auto flex min-w-0 items-center gap-2" />
      <Button
        asChild
        variant="outline"
        size="sm"
        className={cn(TOOLBAR_BUTTON_CLASS, "shrink-0")}
      >
        <Link href={`/admin/tournaments/${summary.id}/registration/rank-autofill`}>
          <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {t("autofill")}
        </Link>
      </Button>
    </header>
  );
}
