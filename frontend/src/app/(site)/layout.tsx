import React from "react";
import { cookies, headers } from "next/headers";
import Header from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Separator } from "@/components/ui/separator";
import workspaceService from "@/services/workspace.service";
import { deriveWorkspacePalette } from "@/lib/workspace-theme";
import { WorkspaceThemeSync } from "@/components/WorkspaceThemeSync";
import { WorkspaceHostLock } from "@/components/WorkspaceHostLock";
import {
  getTournamentOwnerWorkspace,
  tournamentIdFromPathname,
} from "./tournaments/[id]/_data";
import type { Workspace } from "@/types/workspace.types";

// Resolve the current workspace server-side. On a tenant (white-label) host
// `middleware.ts` (Task 6) injects `x-owt-workspace-id` — authoritative, host
// beats cookie — so the palette seed and the tenant header logo both follow the
// host, not a stale cookie. On the apex we fall back to the workspace cookie
// (legacy `aqt-` as a second fallback). Failures degrade to null.
async function resolveCurrentWorkspace(): Promise<Workspace | null> {
  try {
    const h = await headers();
    const cookieStore = await cookies();
    const raw =
      h.get("x-owt-workspace-id") ??
      cookieStore.get("owt-workspace-id")?.value ??
      cookieStore.get("aqt-workspace-id")?.value;
    const id = raw ? Number(raw) : NaN;
    if (!Number.isFinite(id)) return null;
    return await workspaceService.getById(id);
  } catch {
    return null;
  }
}

export default async function SiteLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const requestHeaders = await headers();
  const tenantMode = requestHeaders.get("x-owt-host-mode") === "tenant";
  const workspace = await resolveCurrentWorkspace();

  // A tournament may belong to a workspace other than the one the viewer has
  // selected; its pages must paint the owner's brand. Resolve the owner here so
  // the SSR seed is already correct (flash-free) — the client keeps it in sync
  // via TournamentThemeScope for soft navigations. Never re-theme a locked
  // tenant (white-label) host: its brand is fixed by the request host.
  let seedWorkspace: Workspace | null = workspace;
  if (!tenantMode) {
    const tournamentId = tournamentIdFromPathname(requestHeaders.get("x-owt-pathname") ?? "");
    if (tournamentId !== null) {
      seedWorkspace = (await getTournamentOwnerWorkspace(tournamentId)) ?? workspace;
    }
  }

  // Branding seed for a flash-free first paint (no-op when the workspace has no
  // custom palette).
  const seed = seedWorkspace ? deriveWorkspacePalette(seedWorkspace) : null;
  const style: React.CSSProperties | undefined = seed
    ? ({ ...seed, backgroundColor: "var(--aqt-bg)" } as React.CSSProperties)
    : undefined;

  // On a tenant host the workspace switcher is replaced by the workspace's own
  // logo (icon + name) linking home; on the apex the switcher is shown.
  const tenantWorkspace =
    tenantMode && workspace
      ? { name: workspace.name, iconUrl: workspace.icon_url }
      : undefined;

  return (
    <div className="site-theme min-h-screen w-full" style={style}>
      <WorkspaceHostLock workspaceId={tenantMode && workspace ? workspace.id : null} />
      <WorkspaceThemeSync />
      <div className="w-full max-w-screen-3xl pt-6 mx-auto px-4 md:px-6 xl:px-10 h-full">
        <Header tenantMode={tenantMode} tenantWorkspace={tenantWorkspace} />
        <div className="flex w-full flex-col min-h-[95%]">
          <main className="flex flex-1 flex-col gap-4 pt-4 md:gap-8 md:pt-8">
            {children}
          </main>
        </div>
        <Separator className="mt-8" />
        <Footer />
      </div>
    </div>
  );
}
