import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "legal.privacy.metaTitle",
    descriptionKey: "legal.privacy.metaDescription"
  });
}

export default function PrivacyLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
