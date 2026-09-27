import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "users.compare.title",
    descriptionKey: "users.compare.meta.description"
  });
}

export default function UsersCompareLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
