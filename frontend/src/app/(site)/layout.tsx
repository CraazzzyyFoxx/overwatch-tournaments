import React from "react";
import { cookies, headers } from "next/headers";
import Header from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Separator } from "@/components/ui/separator";
import workspaceService from "@/services/workspace.service";
import { deriveWorkspacePalette } from "@/lib/workspace-theme";
import { WorkspaceThemeSync } from "@/components/WorkspaceThemeSync";
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
  const tenantMode = (await headers()).get("x-owt-host-mode") === "tenant";
  const workspace = await resolveCurrentWorkspace();

  // Branding seed for a flash-free first paint (no-op when the workspace has no
  // custom palette).
  const seed = workspace ? deriveWorkspacePalette(workspace) : null;
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
      <WorkspaceThemeSync />
      <div className="w-full max-w-screen-3xl mt-6 mx-auto px-4 md:px-6 xl:px-10 h-full">
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
