import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Home } from "lucide-react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";

/**
 * Shown when a host is served by the app but is not mapped to any workspace.
 * Nothing on the page is actionable within this workspace, so the only recovery
 * offered is the platform home page.
 */
export default async function NotConfigured() {
  const t = await getTranslations();

  return (
    <div className="mx-auto max-w-md space-y-4 py-16">
      <PageStateCard
        state="not-found"
        headingLevel={1}
        title={t("notConfigured.title")}
        description={t("notConfigured.description")}
      />
      <div className="flex justify-center">
        <Button asChild variant="outline">
          <Link href="/">
            <Home className="size-4" aria-hidden="true" />
            {t("common.homeLink")}
          </Link>
        </Button>
      </div>
    </div>
  );
}
