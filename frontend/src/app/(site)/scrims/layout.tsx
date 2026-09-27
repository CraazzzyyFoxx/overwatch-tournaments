import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "scrims.hero.title",
    descriptionKey: "scrims.meta.description"
  });
}

export default function ScrimsLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
