// Achievement-specific global CSS, loaded with this route's chunk rather than
// from globals.css (where it used to sit, on every page in the app).
import "./achievements.css";

import type { Metadata } from "next";
import React from "react";

import { buildSiteRouteMetadata } from "@/lib/site/route-metadata";

export function generateMetadata(): Promise<Metadata> {
  return buildSiteRouteMetadata({
    titleKey: "achievements.title",
    descriptionKey: "achievements.meta.description"
  });
}

export default function AchievementsLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
