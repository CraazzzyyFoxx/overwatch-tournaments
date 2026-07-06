import React from "react";
import { cookies } from "next/headers";
import Header from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Separator } from "@/components/ui/separator";
import workspaceService from "@/services/workspace.service";
import { deriveWorkspacePalette, type CssVarMap } from "@/lib/workspace-theme";
import { WorkspaceThemeSync } from "@/components/WorkspaceThemeSync";

// Resolve the current workspace's branding server-side (from the same
// `owt-workspace-id` cookie — legacy `aqt-workspace-id` as a fallback — the
// API scoping uses) so the first paint is already themed — no flash. Failures
// degrade to the default palette.
async function resolveSeedPalette(): Promise<CssVarMap | null> {
  try {
    const cookieStore = await cookies();
    const raw = cookieStore.get("owt-workspace-id")?.value ?? cookieStore.get("aqt-workspace-id")?.value;
    const id = raw ? Number(raw) : NaN;
    if (!Number.isFinite(id)) return null;
    const workspace = await workspaceService.getById(id);
    return deriveWorkspacePalette(workspace);
  } catch {
    return null;
  }
}

export default async function SiteLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const seed = await resolveSeedPalette();
  const style: React.CSSProperties | undefined = seed
    ? ({ ...seed, backgroundColor: "var(--aqt-bg)" } as React.CSSProperties)
    : undefined;

  return (
    <div className="site-theme min-h-screen w-full" style={style}>
      <WorkspaceThemeSync />
      <div className="w-full max-w-screen-3xl mt-6 mx-auto px-4 md:px-6 xl:px-10 h-full">
        <Header />
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
