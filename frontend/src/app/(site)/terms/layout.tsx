import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "legal.terms.metaTitle",
    descriptionKey: "legal.terms.metaDescription"
  });
}

export default function TermsLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
