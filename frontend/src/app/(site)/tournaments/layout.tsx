import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "common.tournaments",
    descriptionKey: "tournamentsList.meta.description"
  });
}

export default function TournamentsLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
