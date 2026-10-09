import type { ReactNode } from "react";
import { headers } from "next/headers";

import { BalancerLayoutClient } from "@/app/balancer/BalancerLayoutClient";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";
import { WorkspaceHostLock } from "@/components/workspace/WorkspaceHostLock";
import { WorkspaceThemeSync } from "@/components/workspace/WorkspaceThemeSync";
import workspaceService from "@/services/workspace.service";

type BalancerLayoutProps = {
  children: ReactNode;
};

export default async function BalancerLayout({ children }: Readonly<BalancerLayoutProps>) {
  const requestHeaders = await headers();
  const tenantId = requestHeaders.get("x-owt-workspace-id");
  const tenantWorkspace = requestHeaders.get("x-owt-host-mode") === "tenant" && tenantId
    ? await workspaceService.getById(Number(tenantId))
    : null;
  return (
    <ZoneIntlProvider zone="tools">
      <WorkspaceHostLock workspaceId={tenantWorkspace?.id ?? null} />
      <WorkspaceThemeSync />
      <BalancerLayoutClient tenantWorkspace={tenantWorkspace}>{children}</BalancerLayoutClient>
    </ZoneIntlProvider>
  );
}
