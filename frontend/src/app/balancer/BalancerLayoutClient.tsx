"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { BalancerToolTopBar } from "@/app/balancer/BalancerToolTopBar";
import { BalancerShell } from "@/app/balancer/components/BalancerShell";
import { useToolContext } from "@/app/balancer/useToolContext";
import { Footer } from "@/components/Footer";
import Header from "@/components/Header";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { adminEntryPermissions } from "@/lib/auth/admin-permissions";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

// Shell-shaped: a top-bar strip over one content area, so the frame doesn't jump when it lands.
function LoadingState() {
  const t = useTranslations("balancerTool.page.layout");
  return (
    <div role="status" className="flex h-screen w-full flex-col">
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden className="flex h-12 shrink-0 items-center gap-3 border-b border-border/50 px-4 md:px-5">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-4 w-40" />
        <Skeleton className="ml-auto h-8 w-28" />
      </div>
      <div aria-hidden className="flex flex-1 p-3 md:p-4">
        <Skeleton className="flex-1 rounded-xl" />
      </div>
    </div>
  );
}

function UnauthorizedState() {
  const t = useTranslations("balancerTool.page.layout");
  return (
    <main className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">{t("unauthorizedTitle")}</h1>
        <p className="mt-4 text-muted-foreground">{t("unauthorizedDescription")}</p>
        <p className="mt-2 text-sm text-muted-foreground">{t("unauthorizedContact")}</p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {t("goHome")}
        </Link>
      </div>
    </main>
  );
}

function NoTournamentState() {
  const t = useTranslations("balancerTool.page.layout");
  return (
    <main className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">{t("noTournamentTitle")}</h1>
        <p className="mt-4 text-muted-foreground">{t("noTournamentDescription")}</p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Link
            href="/admin/tournaments"
            className="inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            {t("openTournament")}
          </Link>
          <Link
            href="/balancer/mix"
            className="inline-block rounded-md border border-border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted"
          >
            {t("mixes")}
          </Link>
        </div>
      </div>
    </main>
  );
}

type BalancerLayoutClientProps = {
  children: ReactNode;
  tenantWorkspace?: Workspace | null;
};

export function BalancerLayoutClient({ children, tenantWorkspace }: Readonly<BalancerLayoutClientProps>) {
  const t = useTranslations("balancerTool");
  const pathname = usePathname();
  const { isLoaded, canAccessAdminRoute } = usePermissions();
  const { status: contextStatus, summary } = useToolContext();
  const isMix = pathname.startsWith("/balancer/mix");
  const hostWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);

  if (isMix) {
    if (!isLoaded || (tenantWorkspace != null && hostWorkspaceId !== tenantWorkspace.id)) {
      return <LoadingState />;
    }
    // Viewing a mix is public -- signed out included, so this branch runs
    // before every permission gate below. Only hosting one
    // (create/update/delete) needs the `custom_game` grant, gated inside the
    // mix pages and the balancer-service RPCs themselves.
    //
    // The tool used to replace the site shell entirely (its own top bar, a
    // separate admin palette, a fixed full-viewport frame). Hosting a mix is a
    // member-level grant, read by the same audience as the rest of the site,
    // so it renders as one: the real `Header`/`Footer` on the site's own
    // `--aqt-*` tokens, document flow that scrolls like every other page
    // instead of a viewport-locked frame with two internally-scrolling panels.
    return (
      <div className="site-theme min-h-screen w-full">
        <div className="mx-auto h-full w-full max-w-site px-4 md:px-6 xl:px-10">
          <Header tenantMode={tenantWorkspace != null} tenantWorkspace={tenantWorkspace ?? undefined} />
          <div className="flex w-full flex-col min-h-[95%]">
            <main
              id="main-content"
              tabIndex={-1}
              className="flex flex-1 flex-col gap-4 pt-4 md:gap-8 md:pt-8"
            >
              <BalancerShell>{children}</BalancerShell>
            </main>
          </div>
          <Footer tenant={tenantWorkspace ?? null} />
        </div>
      </div>
    );
  }

  // Render gate (D29, Risk 1): children fire apiFetch calls that inject
  // workspace_id from the store, so nothing below may render until the
  // tournament context is resolved AND the store is aligned to it. A
  // layout-wide gate is simpler and safer than per-hook `enabled` flags.
  if (!isLoaded || contextStatus === "loading") {
    return <LoadingState />;
  }

  if (contextStatus === "missing" || contextStatus === "not_found") {
    return <NoTournamentState />;
  }

  // The entry predicate is unchanged, but the workspace comes from the
  // resolved summary, not the store (the store may still be switching).
  const hasAccess =
    summary != null &&
    canAccessAdminRoute({
      permissions: adminEntryPermissions,
      workspaceId: summary.workspace_id,
      workspaceAdminVisible: true
    });

  if (contextStatus === "forbidden" || !hasAccess) {
    return <UnauthorizedState />;
  }

  if (summary == null) {
    // Unreachable once contextStatus is "ready", but keeps the render below total.
    return <LoadingState />;
  }

  return (
    // `xl:fixed inset-0` takes the tool out of flow, so nothing inside it — however a descendant
    // sizes itself — can add height to the document. `h-svh` + `overflow-hidden` alone only clip:
    // the shell still occupies flow, and any sibling or mis-sized subtree brings back a page
    // scrollbar on top of the app shell. Below `xl` the tool stacks and scrolls normally.
    <div className="flex min-h-svh flex-col bg-background/95 xl:fixed xl:inset-0 xl:h-svh xl:min-h-0 xl:overflow-hidden">
      <BalancerToolTopBar summary={summary} />
      <main className="flex flex-1 flex-col gap-4 overflow-x-hidden p-3 xl:min-h-0 xl:overflow-hidden md:p-4">
        <h1 className="sr-only">{t("title", { tournament: summary.name })}</h1>
        <BalancerShell>{children}</BalancerShell>
      </main>
    </div>
  );
}
