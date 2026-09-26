import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

// The invite token lives in the URL fragment, but the landing page itself is
// still a private link: it exists for one recipient, not for search.
export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "registrationTeams.invite.meta.title",
    descriptionKey: "registrationTeams.invite.meta.description",
    noIndex: true
  });
}

export default function InviteLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
