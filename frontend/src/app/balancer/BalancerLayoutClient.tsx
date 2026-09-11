"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BalancerToolTopBar } from "@/app/balancer/BalancerToolTopBar";
import { BalancerShell } from "@/app/balancer/components/BalancerShell";
import { useToolContext } from "@/app/balancer/useToolContext";
import { Footer } from "@/components/Footer";
import Header from "@/components/Header";
import { Separator } from "@/components/ui/separator";
import { adminEntryPermissions } from "@/lib/admin-permissions";
import { usePermissions } from "@/hooks/usePermissions";

function LoadingState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <div className="inline-block size-8 animate-spin rounded-full border-4 border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]" />
        <p className="mt-4 text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

function UnauthorizedState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Unauthorized</h1>
        <p className="mt-4 text-muted-foreground">
          The balancer workspace is available only to admins and tournament organizers.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Please contact an administrator if you believe this is an error.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Go Home
        </Link>
      </div>
    </div>
  );
}

function NoTournamentState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">No tournament selected</h1>
        <p className="mt-4 text-muted-foreground">
          Open the balancer from a tournament, or manage workspace mixes.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Link
            href="/admin/tournaments"
            className="inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Open a tournament
          </Link>
          <Link
            href="/balancer/mix"
            className="inline-block rounded-md border border-border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted"
          >
            Mixes
          </Link>
        </div>
      </div>
    </div>
  );
}

type BalancerLayoutClientProps = {
  children: ReactNode;
};

export function BalancerLayoutClient({ children }: Readonly<BalancerLayoutClientProps>) {
  const pathname = usePathname();
  const { isLoaded, isOrganizer, canAccessAdminRoute } = usePermissions();
  const { status: contextStatus, summary } = useToolContext();
  const isMix = pathname.startsWith("/balancer/mix");

  if (isMix) {
    if (!isLoaded) {
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
        <div className="mx-auto h-full w-full max-w-screen-3xl px-4 pt-6 md:px-6 xl:px-10">
          <Header />
          <div className="flex w-full flex-col min-h-[95%]">
            <main
              id="main-content"
              tabIndex={-1}
              className="flex flex-1 flex-col gap-4 pt-4 md:gap-8 md:pt-8"
            >
              <BalancerShell>{children}</BalancerShell>
            </main>
          </div>
          <Separator className="mt-8" />
          <Footer />
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
  const hasAdminAccess =
    summary != null &&
    canAccessAdminRoute({
      permissions: adminEntryPermissions,
      workspaceId: summary.workspace_id,
      workspaceAdminVisible: true
    });
  const hasAccess = hasAdminAccess || isOrganizer;

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
      <div className="flex flex-1 flex-col gap-4 overflow-x-hidden p-3 xl:min-h-0 xl:overflow-hidden md:p-4">
        <BalancerShell>{children}</BalancerShell>
      </div>
    </div>
  );
}
